"""A thin, synchronous CalDAV client.

Synchronous on purpose: the app is co-located with Radicale, writes go straight
through (spec §3, no outbox), and the write path needs unmediated control over
etags and raw bodies (invariant #2). FastAPI calls this from a threadpool.

hrefs are kept as the server returns them — server-absolute paths like
``/testuser/<uid>.ics``. They are resolved to absolute URLs only at request time.
Etags are stored verbatim (quotes included) so ``If-Match`` echoes them exactly.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from . import xml as X
from .errors import (
    AuthError,
    Conflict,
    DavError,
    InvalidSyncToken,
    NotFound,
    PreconditionFailed,
)


@dataclass
class Item:
    href: str
    etag: str
    data: bytes | None = None          # raw .ics body; None when only etag was fetched


@dataclass
class CollectionInfo:
    href: str                          # server-absolute path, e.g. /testuser/<id>/
    displayname: str
    components: set[str] = field(default_factory=set)
    color: str | None = None           # apple ical calendar-color, e.g. #FF9500FF
    order: int | None = None           # apple ical calendar-order (client sort hint)

    @property
    def is_task_list(self) -> bool:
        return "VTODO" in self.components and "VEVENT" not in self.components


@dataclass
class SyncResult:
    token: str
    changed: list[Item]                # href + etag (no body); fetch bodies via multiget
    removed: list[str]                 # hrefs deleted since the last token


def _etag(value: str | None) -> str:
    """Normalise an etag for storage/comparison: trim whitespace, keep quotes."""
    return (value or "").strip()


class DavClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
        user_agent: str = "tasksd/0.1 (+phase0)",
    ):
        sp = urlsplit(base_url)
        self.origin = f"{sp.scheme}://{sp.netloc}"
        self.username = username
        self._http = httpx.Client(
            auth=httpx.BasicAuth(username, password),
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )

    # -- lifecycle --
    def __enter__(self) -> "DavClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- url helpers --
    def abs(self, href: str) -> str:
        if href.startswith(("http://", "https://")):
            return href
        return urljoin(self.origin + "/", href.lstrip("/"))

    @property
    def principal_path(self) -> str:
        return f"/{self.username}/"

    # -- low level --
    def _request(
        self,
        method: str,
        href: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] | None = None,
    ) -> httpx.Response:
        hdrs: dict[str, str] = {}
        if content is not None:
            hdrs["Content-Type"] = "application/xml; charset=utf-8"
        if headers:
            hdrs.update(headers)
        try:
            resp = self._http.request(method, self.abs(href), content=content, headers=hdrs)
        except httpx.HTTPError as e:
            # Connection refused / timeout / TLS — same taxonomy as HTTP-level
            # failures so callers (and the API's 502 mapping) see one error type.
            raise DavError(f"transport error on {method} {href}: {e}") from e
        if expected is not None and resp.status_code not in expected:
            _raise_for(resp)
        return resp

    # -- discovery --
    def options(self) -> set[str]:
        resp = self._request("OPTIONS", self.principal_path, expected={200, 204})
        return {m.strip() for m in resp.headers.get("Allow", "").split(",") if m.strip()}

    def list_collections(self) -> list[CollectionInfo]:
        body = X.build_propfind([
            X.DISPLAYNAME, X.RESOURCETYPE, X.SUPPORTED_COMPONENT_SET,
            X.CALENDAR_COLOR, X.CALENDAR_ORDER,
        ])
        resp = self._request(
            "PROPFIND", self.principal_path, content=body, headers={"Depth": "1"}, expected={207}
        )
        out: list[CollectionInfo] = []
        for r in X.parse_multistatus(resp.content).responses:
            rt = r.prop(X.RESOURCETYPE)
            if rt is None or rt.find(X.CALENDAR) is None:
                continue
            comps: set[str] = set()
            comp_set = r.prop(X.SUPPORTED_COMPONENT_SET)
            if comp_set is not None:
                comps = {
                    c.get("name", "").upper() for c in comp_set.findall(X.COMP) if c.get("name")
                }
            name = r.text(X.DISPLAYNAME) or r.href.rstrip("/").rsplit("/", 1)[-1]
            color = (r.text(X.CALENDAR_COLOR) or "").strip() or None
            order_text = (r.text(X.CALENDAR_ORDER) or "").strip()
            try:
                order = int(order_text) if order_text else None
            except ValueError:
                order = None
            out.append(CollectionInfo(
                href=r.href, displayname=name, components=comps, color=color, order=order
            ))
        return out

    # -- collection creation (the VTODO-only MKCALENDAR helper, invariant #8) --
    def create_task_collection(
        self, displayname: str, *, components: tuple[str, ...] = ("VTODO",), **kw: str
    ) -> CollectionInfo:
        href = f"{self.principal_path}{uuid.uuid4().hex}/"
        self.mkcalendar(href, displayname, components=components, **kw)
        return CollectionInfo(
            href=href, displayname=displayname, components={c.upper() for c in components}
        )

    def mkcalendar(
        self, href: str, displayname: str, *, components: tuple[str, ...] = ("VTODO",), **kw: str
    ) -> None:
        body = X.build_mkcalendar(displayname, list(components), **kw)
        self._request("MKCALENDAR", href, content=body, expected={201})

    def delete_collection(self, href: str) -> None:
        self._request("DELETE", href, expected={200, 204, 404})

    def proppatch(self, href: str, props: dict[str, str | None]) -> None:
        """PROPPATCH dead properties on a collection (displayname, calendar-color,
        calendar-order). A ``None`` value removes the property."""
        if not props:
            return
        body = X.build_proppatch(props)
        resp = self._request("PROPPATCH", href, content=body, expected={207})
        for r in X.parse_multistatus(resp.content).responses:
            for ps in r.propstats:
                if ps.props and not (200 <= ps.status < 300):
                    failed = ", ".join(ps.props)
                    raise DavError(
                        f"PROPPATCH {href} rejected ({ps.status}) for: {failed}",
                        status=ps.status,
                    )

    # -- item read --
    def get(self, href: str) -> Item:
        resp = self._request("GET", href, expected={200})
        return Item(href=href, etag=_etag(resp.headers.get("ETag")), data=resp.content)

    def head_etag(self, href: str) -> str:
        resp = self._request("HEAD", href, expected={200})
        return _etag(resp.headers.get("ETag"))

    # -- item write --
    def put(
        self,
        href: str,
        data: bytes,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> str:
        """PUT a raw body. Returns the new etag.

        Pass ``if_match`` with the last-known etag for edits (invariant #5) or
        ``if_none_match='*'`` to create-only. Never blind-overwrite.
        """
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if if_match is not None:
            headers["If-Match"] = if_match
        if if_none_match is not None:
            headers["If-None-Match"] = if_none_match
        resp = self._request("PUT", href, content=data, headers=headers, expected={201, 204})
        etag = _etag(resp.headers.get("ETag"))
        return etag or self.head_etag(href)     # Radicale may omit ETag on PUT

    def delete(self, href: str, *, if_match: str | None = None) -> None:
        headers = {"If-Match": if_match} if if_match is not None else {}
        # 404 is fine — the goal (absence) is already achieved.
        self._request("DELETE", href, headers=headers, expected={200, 204, 404})

    # -- sync --
    def sync_collection(self, collection_href: str, sync_token: str | None = None) -> SyncResult:
        """RFC 6578 sync-collection REPORT.

        ``sync_token=None`` (empty token) performs an initial/full enumeration and
        returns a fresh token atomically. A pruned/invalid token raises
        InvalidSyncToken — the caller falls back to a full resync (invariant #6).
        """
        body = X.build_sync_collection(sync_token, [X.GETETAG])
        resp = self._request("REPORT", collection_href, content=body, headers={"Depth": "1"})
        if resp.status_code != 207:
            if _looks_like_invalid_token(resp):
                raise InvalidSyncToken(
                    f"sync token rejected ({resp.status_code})",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            _raise_for(resp)
        ms = X.parse_multistatus(resp.content)
        if ms.sync_token is None:
            raise DavError("sync-collection response had no sync-token")
        changed, removed = [], []
        for r in ms.responses:
            if r.is_removed:
                removed.append(r.href)
            else:
                changed.append(Item(href=r.href, etag=_etag(r.text(X.GETETAG))))
        return SyncResult(token=ms.sync_token, changed=changed, removed=removed)

    def list_etags(self, collection_href: str) -> dict[str, str]:
        """PROPFIND Depth:1 -> {href: etag} for every item (collection excluded).

        The token-independent enumeration used by the full-resync fallback and by
        orphan/GC reconciliation.
        """
        body = X.build_propfind([X.GETETAG])
        resp = self._request(
            "PROPFIND", collection_href, content=body, headers={"Depth": "1"}, expected={207}
        )
        out: dict[str, str] = {}
        for r in X.parse_multistatus(resp.content).responses:
            etag = r.text(X.GETETAG)
            if etag is not None:                 # the collection itself has no getetag
                out[r.href] = _etag(etag)
        return out

    def multiget(self, collection_href: str, hrefs: list[str]) -> list[Item]:
        """calendar-multiget REPORT -> items with bodies. Missing hrefs are skipped."""
        if not hrefs:
            return []
        body = X.build_calendar_multiget(hrefs, [X.GETETAG, X.CALENDAR_DATA])
        resp = self._request(
            "REPORT", collection_href, content=body, headers={"Depth": "1"}, expected={207}
        )
        out: list[Item] = []
        for r in X.parse_multistatus(resp.content).responses:
            if r.is_removed:
                continue
            data_el = r.prop(X.CALENDAR_DATA)
            if data_el is not None and data_el.text:
                out.append(
                    Item(href=r.href, etag=_etag(r.text(X.GETETAG)), data=data_el.text.encode())
                )
        return out


def _looks_like_invalid_token(resp: httpx.Response) -> bool:
    """RFC 6578 says an invalid token yields 403 + DAV:valid-sync-token. Servers
    vary (some 400/409). Detect by status family and/or the precondition name."""
    if resp.status_code in (400, 403, 409) and b"valid-sync-token" in resp.content:
        return True
    return b"valid-sync-token" in resp.content


def _raise_for(resp: httpx.Response) -> None:
    status = resp.status_code
    msg = f"{resp.request.method} {resp.request.url} -> {status}"
    body = resp.text[:500]
    if status in (401, 403):
        raise AuthError(msg, status=status, body=body)
    if status == 404:
        raise NotFound(msg, status=status, body=body)
    if status == 409:
        raise Conflict(msg, status=status, body=body)
    if status == 412:
        raise PreconditionFailed(msg, status=status, body=body)
    raise DavError(msg, status=status, body=body)
