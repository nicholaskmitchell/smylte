"""The MCP endpoint itself: JSON-RPC over Streamable HTTP.

Hand-rolled rather than built on the MCP SDK, for the same reason the CalDAV
client is: the surface actually needed here is small and completely specified,
and owning it keeps the authorization path — which is the part that matters —
free of a framework's own ideas about who the caller is. What the spec asks of a
Streamable HTTP server, minus the parts a stateless server does not use, is
about two hundred lines.

Stateless by choice. The spec makes sessions optional (`Mcp-Session-Id` is
assigned "MAY"), and every request already carries a bearer token that has to be
validated on its own merits anyway. Refusing to hold session state means there
is nothing to hijack, nothing to expire, and no way for a reconnect to land on
someone else's context.

`POST` returns a single JSON object rather than an SSE stream. Nothing here
pushes: every tool answers immediately from local SQLite or one CalDAV round
trip. `GET` therefore answers 405, which the spec names as the correct reply
from a server that offers no server-initiated stream — and which also sidesteps
the long-lived-stream authorization problem the app already has on /api/events,
where the token is checked once at connect and never again.
"""
from __future__ import annotations

import json
import logging
import math

from .oauth import OAuthError, SCOPE_WRITE, scope_set
from .tools import ToolError, build_tools
from .validate import SchemaError, check_arguments

log = logging.getLogger("tasksd.mcp")

# Revisions this server can speak. The client names one in `initialize`; we echo
# it back when we know it, and otherwise answer with our newest and let the
# client decide — which is what the lifecycle spec prescribes.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]

SERVER_INFO = {"name": "smylte", "title": "Smylte", "version": "1.0.0"}

# JSON-RPC 2.0
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# A tool result is JSON in a text block. Bounded so one wide query cannot bury
# the client's context — the tools paginate, this is the backstop if one ever
# forgets to.
MAX_RESULT_CHARS = 400_000

# Messages in one batch. The transport caps the BODY at 1 MB, which bounds the
# bytes but not the work: `tools/list` is ~40 bytes of JSON, so one compliant
# request was ~25 000 messages — each a full CalDAV/SQLite call, dispatched
# serially under the global service lock, with every reply accumulated in memory
# before any of it was sent. The real question a batch cap answers is "how long
# may one request hold the server", so it is a message count, not a byte count.
# 50 matches DEFAULT_LIMIT and is far above what clients actually send (1-10).
MAX_BATCH = 50


def _usable_id(rid) -> bool:
    """Whether an id can be echoed back. JSON-RPC 2.0 §4 allows a String, a
    Number or Null; `bool` is excluded because it is not a Number, and a float
    has to be finite or the response cannot be serialized at all."""
    if rid is None or isinstance(rid, str):
        return True
    if isinstance(rid, bool):
        return False
    if isinstance(rid, int):
        return True
    return isinstance(rid, float) and math.isfinite(rid)


def _result(rid, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _error(rid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


class McpServer:
    """Dispatch for one account's MCP endpoint.

    `run` is synchronous and does the SQLite/CalDAV work, so callers hop it to a
    thread exactly like every other route in this app.
    """

    def __init__(self, api):
        self.tools = build_tools(api)

    # ── protocol ─────────────────────────────────────────────────────────────

    def handle(self, message: dict, *, scopes: set[str]) -> dict | None:
        """One JSON-RPC message in, one response out — or None for a
        notification, which by definition has no reply."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 message")
        method = message.get("method")
        rid = message.get("id")
        if not _usable_id(rid):
            # The id is a REPLY ADDRESS, and it is echoed into every envelope
            # this returns. A non-finite float survives json.loads and dies in
            # json.dumps — Starlette renders with allow_nan=False — so echoing
            # one raised while rendering, outside every exception handler, and
            # the request became a 500. For tools/call that lands AFTER the tool
            # has run, so a real write committed while its caller was told the
            # call failed; in a batch, one poisoned id discarded all 50 replies.
            # Answer against a null id, the shape run_batch already uses when it
            # cannot address the caller. (app.py's _invalid_request documents
            # this same trap on the 422 path.)
            return _error(None, INVALID_REQUEST,
                          "id must be a string, a finite number, or null")
        if not isinstance(method, str):
            return _error(rid, INVALID_REQUEST, "missing method")
        # No id means a notification. The only ones that matter here are
        # `notifications/initialized` and cancellation, and a stateless server
        # has nothing to do for either — but it must not reply.
        is_notification = "id" not in message

        try:
            if method == "initialize":
                payload = self._initialize(message.get("params") or {})
            elif method == "ping":
                payload = {}
            elif method == "tools/list":
                payload = {"tools": [t.descriptor() for t in self.tools.values()]}
            elif method == "tools/call":
                payload = self._call(message.get("params") or {}, scopes)
            elif method in ("resources/list", "prompts/list"):
                # Advertised nowhere, but clients probe them anyway; an empty
                # list is friendlier than "method not found".
                payload = {"resources": []} if method.startswith("resources") else {"prompts": []}
            elif method.startswith("notifications/"):
                return None
            else:
                return None if is_notification else _error(
                    rid, METHOD_NOT_FOUND, f"unknown method: {method}"
                )
        except OAuthError:
            raise                                  # authorization is the transport's business
        except ToolError as exc:
            return None if is_notification else _error(rid, INVALID_PARAMS, str(exc))
        except Exception as exc:                   # noqa: BLE001
            # Logged in full, reported in outline: the message may carry a
            # CalDAV URL or a backend detail the client has no business seeing.
            log.exception("mcp: %s failed", method)
            return None if is_notification else _error(
                rid, INTERNAL_ERROR, f"{method} failed: {type(exc).__name__}"
            )
        return None if is_notification else _result(rid, payload)

    def _initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Smylte is this person's own tasks and calendar, stored on their "
                "CalDAV server. Task tools need a list id from smylte_list_lists; "
                "event tools need a calendar id from smylte_list_calendars. "
                "Writes are real and visible in their other clients immediately, "
                "so confirm before deleting anything."
            ),
        }

    # ── tools ────────────────────────────────────────────────────────────────

    def _call(self, params: dict, scopes: set[str]) -> dict:
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise ToolError(
                f"There is no tool called {name!r}. Call tools/list to see what exists."
            )
        if tool.scope not in scopes:
            # Not a tool error: the grant is too narrow, and the model can no
            # more fix that by rephrasing than by trying again. Say so plainly.
            need = "write" if tool.scope == SCOPE_WRITE else "read"
            raise ToolError(
                f"{name} needs {need} access, which this connection was not "
                f"granted. Reconnect the Smylte connector and approve "
                f"{tool.scope} to use it."
            )
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")

        # The schema is advertised, but a client is not obliged to honour it and a
        # buggy or hostile one will not — so it is enforced here rather than
        # trusted. Everything downstream was written behind FastAPI, where
        # pydantic had already checked these bounds; without this the published
        # contract is decoration. See validate.py for what that cost.
        try:
            check_arguments(args, tool.schema, tool=name)
        except SchemaError as exc:
            raise ToolError(str(exc)) from None

        try:
            value = tool.handler(**args)
        except ToolError as exc:
            return self._tool_failure(str(exc))
        except TypeError as exc:
            return self._tool_failure(f"{name} rejected those arguments: {exc}")
        except Exception as exc:                   # noqa: BLE001
            log.exception("mcp: tool %s failed", name)
            return self._tool_failure(
                f"{name} could not be completed ({type(exc).__name__}). The "
                f"calendar server may be unreachable; try again shortly."
            )

        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            return self._tool_failure(
                f"That result is too large to return ({len(text)} characters). "
                f"Narrow the range, or use limit and offset to page through it."
            )
        return {
            "content": [{"type": "text", "text": text}],
            # Modern clients read this and skip re-parsing the text block; older
            # ones ignore it. Both get the same data.
            "structuredContent": value if isinstance(value, dict) else {"result": value},
            "isError": False,
        }

    @staticmethod
    def _tool_failure(message: str) -> dict:
        """A failure the model should read.

        Reported as a *successful* JSON-RPC result carrying `isError` — which is
        the protocol's own distinction: a JSON-RPC error means the call could not
        be made, while this means it was made and did not work. The model sees
        the sentence and can act on it.
        """
        return {"content": [{"type": "text", "text": message}], "isError": True}


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def parse_body(raw: bytes) -> object:
    if len(raw) == 0:
        raise ValueError("empty body")
    try:
        # `parse_constant` catches the bare NaN/Infinity/-Infinity literals here,
        # where the protocol already has an answer for unreadable JSON (-32700),
        # rather than letting them reach a response that cannot be rendered.
        # It does NOT catch 1e400 — that is an ordinary number literal parsed by
        # `parse_float`, which overflows to inf — so the id-shape check in
        # `handle` is the load-bearing guard and this is defence in depth.
        return json.loads(raw, parse_constant=_reject_constant)
    except RecursionError as exc:
        # `json.loads` recurses per nesting level, and RecursionError is a
        # RuntimeError — not a ValueError — so deeply nested JSON escaped the
        # transport's parse guard and 500ed instead of answering -32700.
        # Normalised here rather than at the call site so there stays exactly
        # one parse-failure taxonomy for callers to catch.
        raise ValueError("JSON nested too deeply") from exc


def run_batch(server: McpServer, payload: object, *, scopes: set[str]) -> object | None:
    """Handle one message or a batch, returning what should be sent back.

    Batching left 2025-06-18 but earlier revisions allow it and clients in the
    wild still send it, so it is accepted. A batch of pure notifications has no
    reply at all, which the transport turns into a 202.
    """
    if isinstance(payload, list):
        if not payload:
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": INVALID_REQUEST, "message": "empty batch"}}
        if len(payload) > MAX_BATCH:
            # Refused whole, not truncated: a caller that got results for the
            # first N of its messages and silence for the rest cannot tell the
            # difference between "dropped" and "succeeded with no reply", and
            # would carry on as though the writes had landed.
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": INVALID_REQUEST,
                              "message": f"batch too large: {len(payload)} messages, "
                                         f"limit is {MAX_BATCH}"}}
        out = [r for r in (server.handle(m, scopes=scopes) for m in payload) if r is not None]
        return out or None
    if isinstance(payload, dict):
        return server.handle(payload, scopes=scopes)
    return {"jsonrpc": "2.0", "id": None,
            "error": {"code": INVALID_REQUEST, "message": "expected an object or array"}}
