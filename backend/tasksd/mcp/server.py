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

import inspect
import json
import logging

from .oauth import OAuthError, SCOPE_WRITE, scope_set
from .tools import ToolError, build_tools

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

        # The schema is advertised, but a client is not obliged to honour it, so
        # unknown keys are refused here rather than reaching a handler as a
        # TypeError the model cannot read.
        allowed = set(tool.schema.get("properties", {}))
        unknown = set(args) - allowed
        if unknown:
            raise ToolError(
                f"{name} has no argument(s) {', '.join(sorted(unknown))}. "
                f"It accepts: {', '.join(sorted(allowed)) or 'no arguments'}."
            )
        missing = [k for k in tool.schema.get("required", []) if k not in args]
        if missing:
            raise ToolError(f"{name} is missing required argument(s): {', '.join(missing)}.")

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


def parse_body(raw: bytes) -> object:
    if len(raw) == 0:
        raise ValueError("empty body")
    return json.loads(raw)


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
        out = [r for r in (server.handle(m, scopes=scopes) for m in payload) if r is not None]
        return out or None
    if isinstance(payload, dict):
        return server.handle(payload, scopes=scopes)
    return {"jsonrpc": "2.0", "id": None,
            "error": {"code": INVALID_REQUEST, "message": "expected an object or array"}}
