"""AUREO LINK | private pairing and temporary WebSocket relay.

Python 3.11+ / aiohttp. HTTPS termination is done by a reverse proxy.
Payloads are NOT end-to-end encrypted: the relay can inspect them.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlencode

from aiohttp import WSMsgType, web
from server.directory_client import PHONE_ENTRY

ROOT = Path(__file__).resolve().parent.parent
PWA = ROOT / "pwa"
MAX_FILE_BYTES = 20 * 1024 * 1024
CHUNK_BYTES = 48 * 1024
QR_TTL = 90
MAX_CHAT = 12000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_name(value: object, limit: int = 55) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def safe_filename(value: object) -> str:
    name = str(value or "file").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(". ")[:145]
    name = name.rstrip(". ") or "file"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


class Hub:
    def __init__(self, db_path: Path, public_url: str, enroll_key: str):
        self.public_url = public_url.rstrip("/")
        self.enroll_key = enroll_key
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS desktops (
            id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, name TEXT NOT NULL,
            created TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS mobiles (
            id TEXT PRIMARY KEY, desktop_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created TEXT NOT NULL,
            FOREIGN KEY(desktop_id) REFERENCES desktops(id)
          );
          CREATE INDEX IF NOT EXISTS idx_mobile_desktop ON mobiles(desktop_id);
          DELETE FROM mobiles WHERE rowid NOT IN (SELECT MAX(rowid) FROM mobiles GROUP BY desktop_id);
          CREATE UNIQUE INDEX IF NOT EXISTS idx_one_mobile_per_desktop ON mobiles(desktop_id);
        """)
        self.db.commit()
        if 'portable' not in {r[1] for r in self.db.execute('PRAGMA table_info(mobiles)')}:
            self.db.execute('ALTER TABLE mobiles ADD COLUMN portable INTEGER NOT NULL DEFAULT 0')
            self.db.commit()
        self.publisher = None
        self.pwa_origin = 'https://stu310101-arch.github.io'
        self.desktops: dict[str, web.WebSocketResponse] = {}
        self.mobile_sockets: dict[str, set[web.WebSocketResponse]] = {}
        self.qrs: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.transfers: dict[tuple[int, str], dict] = {}
        self.claim_limiter: dict[str, list[float]] = {}

    def close(self):
        self.db.close()

    def origin_allowed(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin")
        allowed = urlsplit(self.public_url)
        # Browser calls send Origin. Non-browser HTTP agents without an Origin
        # cannot send credentialed cross-site scripts, but still need auth.
        if origin:
            source = urlsplit(origin)
            return origin == self.pwa_origin or (source.scheme, source.netloc) == (allowed.scheme, allowed.netloc)
        return True

    def mobile_auth(self, request: web.Request):
        authorization = request.headers.get('Authorization', '')
        token = authorization[7:] if authorization.startswith('Bearer ') else request.cookies.get("aureo_session", "")
        return self.token_auth(token)

    def token_auth(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
            return None
        return self.db.execute(
            "SELECT m.id,m.desktop_id,m.name,d.name AS desktop_name FROM mobiles m "
            "JOIN desktops d ON d.id=m.desktop_id WHERE m.token_hash=?",
            (digest(token),),
        ).fetchone()

    def desktop_devices(self, desktop_id: str) -> list[dict]:
        rows = self.db.execute("SELECT id,name FROM mobiles WHERE desktop_id=? ORDER BY created", (desktop_id,))
        return [{"id": r["id"], "name": r["name"],
                 "online": bool(self.mobile_sockets.get(r["id"]))} for r in rows]

    async def tell(self, ws: web.WebSocketResponse, packet: dict):
        if not ws.closed:
            try:
                await ws.send_json(packet)
            except (ConnectionError, RuntimeError):
                pass

    async def update_devices(self, desktop_id: str):
        target = self.desktops.get(desktop_id)
        if target:
            await self.tell(target, {"type": "devices", "devices": self.desktop_devices(desktop_id)})

    async def notify_presence(self, desktop_id: str, online: bool):
        mobiles = self.db.execute("SELECT id FROM mobiles WHERE desktop_id=?", (desktop_id,))
        for row in mobiles:
            for ws in list(self.mobile_sockets.get(row["id"], set())):
                await self.tell(ws, {"type": "presence", "online": online})

    def purge_expired(self):
        t = time.monotonic()
        self.qrs = {k: v for k, v in self.qrs.items() if v["expires"] > t}
        self.pending = {k: v for k, v in self.pending.items() if v["expires"] > t}

    async def relay(self, source: web.WebSocketResponse, packet: dict, targets: list[web.WebSocketResponse],
                    sender: str):
        typ = packet.get("type")
        if typ in ("chat", "clipboard"):
            content = packet.get("text")
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_CHAT:
                await self.tell(source, {"type": "error", "message": "文字內容超過限制或為空"})
                return
            if not targets:
                await self.tell(source, {"type": "error", "message": "對方不在線上，訊息未送出"})
                return
            event = {"type": typ, "text": content, "from": sender, "at": now_iso(),
                     "id": secrets.token_hex(8)}
            for target in targets:
                await self.tell(target, event)
            await self.tell(source, {"type": "sent", "id": packet.get("client_id", "")})
            return
        tid = packet.get("id")
        if not isinstance(tid, str) or not (4 <= len(tid) <= 75) or not re.fullmatch(r"[a-zA-Z0-9_-]+", tid):
            await self.tell(source, {"type": "error", "message": "無效傳輸 ID"})
            return
        key = (id(source), tid)
        # Every file error carries its transfer ID so clients can stop its progress UI.
        async def file_error(message):
            await self.tell(source, {"type": "error", "id": tid, "message": message})
        if typ == "file_start":
            size = packet.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or not (0 <= size <= MAX_FILE_BYTES):
                await file_error("檔案超過 20 MB 限制")
                return
            if key in self.transfers or sum(k[0] == id(source) for k in self.transfers) >= 2:
                await file_error("同時最多兩個檔案傳輸")
                return
            if not targets:
                await file_error("對方不在線上，檔案未送出")
                return
            event = {"type": "file_start", "id": tid, "name": safe_filename(packet.get("name")),
                     "size": size, "mime": short_name(packet.get("mime"), 100), "from": sender}
            self.transfers[key] = {"total": size, "received": 0, "next_seq": 0, "targets": targets}
            for target in targets:
                await self.tell(target, event)
        elif typ == "file_chunk":
            state = self.transfers.get(key)
            if not state:
                return
            data = packet.get("data", "")
            seq = packet.get("seq")
            if not isinstance(data, str) or len(data) > 70000 or seq != state["next_seq"]:
                self.transfers.pop(key, None)
                for target in state["targets"]:
                    await self.tell(target, {"type": "file_cancel", "id": tid})
                await file_error("檔案分段資料不正確")
                return
            try:
                raw = base64.b64decode(data, validate=True)
            except (ValueError, binascii.Error):
                raw = b""
            if not raw or len(raw) > CHUNK_BYTES or state["received"] + len(raw) > state["total"]:
                self.transfers.pop(key, None)
                for target in state["targets"]:
                    await self.tell(target, {"type": "file_cancel", "id": tid})
                await file_error("檔案分段超出限制")
                return
            state["received"] += len(raw)
            state["next_seq"] += 1
            for target in state["targets"]:
                await self.tell(target, {"type": "file_chunk", "id": tid, "seq": seq, "data": data})
        elif typ == "file_end":
            state = self.transfers.pop(key, None)
            if not state:
                return
            if state["received"] != state["total"]:
                for target in state["targets"]:
                    await self.tell(target, {"type": "file_cancel", "id": tid})
                await file_error("檔案資料長度不符")
                return
            for target in state["targets"]:
                await self.tell(target, {"type": "file_end", "id": tid})
            await self.tell(source, {"type": "sent", "id": tid})
        else:
            await self.tell(source, {"type": "error", "message": "未知傳輸指令"})

    async def clear_socket_transfers(self, ws: web.WebSocketResponse):
        for key, state in list(self.transfers.items()):
            if key[0] == id(ws):
                for target in state["targets"]:
                    await self.tell(target, {"type": "file_cancel", "id": key[1]})
                self.transfers.pop(key, None)
            elif ws in state['targets']:
                state['targets'] = [target for target in state['targets'] if target is not ws]
                if not state['targets']:
                    self.transfers.pop(key, None)
                    sources = list(self.desktops.values()) + [s for group in self.mobile_sockets.values() for s in group]
                    for source in sources:
                        if id(source) == key[0]:
                            await self.tell(source, {'type': 'error', 'id': key[1],
                                                     'message': '對方已離線，檔案傳送未完成'})
                            break


async def index(request: web.Request):
    hub = request.app['hub']
    if hub.publisher:
        details = {'relay': hub.public_url, 'locator': hub.publisher.locator}
        token = request.query.get('pair', '')
        if re.fullmatch(r'[a-zA-Z0-9_-]{48}', token):
            details['pair'] = token
        raise web.HTTPFound(PHONE_ENTRY + '#' + urlencode(details))
    res = web.FileResponse(PWA / "index.html")
    res.headers["Cache-Control"] = "no-store"
    return res


async def current_user(request: web.Request):
    m = request.app["hub"].mobile_auth(request)
    if not m:
        return web.json_response({"paired": False}, headers={"Cache-Control": "no-store"})
    return web.json_response({"paired": True, "name": m["name"],
                              "desktop_name": m["desktop_name"], "desktop_id": m["desktop_id"]},
                             headers={"Cache-Control": "no-store"})


async def claim(request: web.Request):
    hub: Hub = request.app["hub"]
    if not hub.origin_allowed(request):
        raise web.HTTPForbidden()
    addr = request.remote or "unknown"
    t = time.monotonic()
    history = [x for x in hub.claim_limiter.get(addr, []) if x > t - 60]
    if len(history) >= 12:
        raise web.HTTPTooManyRequests(text="Too many attempts")
    history.append(t)
    hub.claim_limiter[addr] = history
    try:
        req = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON")
    if not isinstance(req, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object")
    token = req.get("code", "")
    if not isinstance(token, str) or not (len(token) == 48 or re.fullmatch(r"[0-9]{8}", token)):
        raise web.HTTPBadRequest(text="Invalid code")
    hub.purge_expired()
    code = hub.qrs.pop(token, None)  # one-time, even if later denied
    if code:
        # 8-digit manual code and QR token represent the same one-use request.
        for alias, item in list(hub.qrs.items()):
            if item is code:
                hub.qrs.pop(alias, None)
    if not code or code["desktop_id"] not in hub.desktops:
        raise web.HTTPGone(text="QR expired or desktop offline")
    if hub.desktop_devices(code['desktop_id']):
        raise web.HTTPConflict(text="A device is already paired; unpair it first")
    if any(p['desktop_id'] == code['desktop_id'] and p['state'] == 'waiting'
           for p in hub.pending.values()):
        raise web.HTTPConflict(text="Another pairing request is pending")
    request_id, proof = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    name = short_name(req.get("name") or "iPhone / 行動裝置", 40)
    hub.pending[request_id] = {"desktop_id": code["desktop_id"], "proof": proof,
                               "name": name, "expires": time.monotonic() + 180, "state": "waiting",
                               "portable": request.headers.get('Origin') == hub.pwa_origin}
    await hub.tell(hub.desktops[code["desktop_id"]],
                   {"type": "pair_request", "request_id": request_id, "name": name})
    return web.json_response({"request_id": request_id, "proof": proof, "status": "waiting"},
                             headers={"Cache-Control": "no-store"})


async def claim_status(request: web.Request):
    hub: Hub = request.app["hub"]
    hub.purge_expired()
    values = await request.json() if request.method == 'POST' else request.query
    if not isinstance(values, dict) and request.method == 'POST':
        raise web.HTTPBadRequest()
    rid = values.get("request_id", "")
    proof = values.get("proof", "")
    pending = hub.pending.get(rid)
    if not pending or not isinstance(proof, str) or not secrets.compare_digest(pending["proof"], proof):
        raise web.HTTPGone(text="Pairing expired")
    if pending.get('portable') and request.headers.get('Origin') != hub.pwa_origin:
        raise web.HTTPForbidden()
    if pending["state"] == "waiting":
        return web.json_response({"status": "waiting"}, headers={"Cache-Control": "no-store"})
    hub.pending.pop(rid, None)
    if pending["state"] != "approved":
        return web.json_response({"status": "denied"}, headers={"Cache-Control": "no-store"})
    data = {"status": "approved"}
    if pending.get('portable'):
        data['token'] = pending['token']
        if hub.publisher:
            data.update(hub.publisher.credentials())
    response = web.json_response(data, headers={"Cache-Control": "no-store"})
    response.set_cookie("aureo_session", pending["token"], httponly=True,
                        secure=hub.public_url.startswith("https://"),
                        samesite="Strict", path="/", max_age=3600 * 24 * 365)
    return response


async def logout(request: web.Request):
    hub: Hub = request.app["hub"]
    if not hub.origin_allowed(request):
        raise web.HTTPForbidden()
    mobile = hub.mobile_auth(request)
    if mobile:
        hub.db.execute("DELETE FROM mobiles WHERE id=?", (mobile["id"],))
        hub.db.commit()
        await hub.update_devices(mobile["desktop_id"])
        for ws in list(hub.mobile_sockets.get(mobile["id"], set())):
            await ws.close(code=4003, message=b"revoked")
    res = web.json_response({"ok": True})
    res.del_cookie("aureo_session", path="/")
    return res


async def desktop_socket(request: web.Request):
    hub: Hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=135000)
    await ws.prepare(request)
    desktop_id = None
    try:
        first = await ws.receive(timeout=12)
        if first.type != WSMsgType.TEXT:
            return ws
        try:
            msg = json.loads(first.data)
        except (ValueError, TypeError):
            return ws
        if not isinstance(msg, dict):
            return ws
        if msg.get("type") != "desktop_hello":
            return ws
        identifier, secret = msg.get("desktop_id"), msg.get("secret")
        name = short_name(msg.get("name") or "Windows 電腦", 40)
        if not isinstance(identifier, str) or not re.fullmatch("[a-f0-9]{32}", identifier):
            await hub.tell(ws, {"type": "error", "message": "桌面裝置 ID 無效"})
            return ws
        if not isinstance(secret, str) or len(secret) != 64:
            await hub.tell(ws, {"type": "error", "message": "桌面密鑰無效"})
            return ws
        old = hub.db.execute("SELECT secret_hash,name FROM desktops WHERE id=?", (identifier,)).fetchone()
        if old:
            if not secrets.compare_digest(old["secret_hash"], digest(secret)):
                await hub.tell(ws, {"type": "error", "message": "桌面認證失敗"})
                return ws
        elif hub.enroll_key and secrets.compare_digest(str(msg.get("enroll_key") or ""), hub.enroll_key):
            hub.db.execute("INSERT INTO desktops VALUES (?,?,?,?)",
                           (identifier, digest(secret), name, now_iso()))
            hub.db.commit()
        else:
            await hub.tell(ws, {"type": "error", "message": "首次註冊需要正確的伺服器註冊密碼"})
            return ws
        desktop_id = identifier
        previous = hub.desktops.get(identifier)
        if previous and previous is not ws:
            await previous.close(code=4001, message=b"replaced")
        hub.desktops[identifier] = ws
        await hub.tell(ws, {"type": "desktop_welcome", "name": name,
                            "devices": hub.desktop_devices(identifier), "limit_mb": 20})
        await hub.notify_presence(identifier, True)
        async for event in ws:
            if event.type != WSMsgType.TEXT:
                continue
            try:
                p = json.loads(event.data)
            except (ValueError, TypeError):
                continue
            if not isinstance(p, dict):
                continue
            kind = p.get("type")
            if kind == "new_qr":
                hub.purge_expired()
                for token, meta in list(hub.qrs.items()):
                    if meta["desktop_id"] == identifier:
                        hub.qrs.pop(token, None)
                devices = hub.desktop_devices(identifier)
                if devices:
                    await hub.tell(ws, {'type': 'pair_locked', 'devices': devices})
                    continue
                if any(p['desktop_id'] == identifier and p['state'] == 'waiting'
                       for p in hub.pending.values()):
                    await hub.tell(ws, {'type': 'pair_waiting'})
                    continue
                code = secrets.token_urlsafe(36)  # normally 48 chars
                pin = f"{secrets.randbelow(90000000) + 10000000:08d}"
                while pin in hub.qrs:
                    pin = f"{secrets.randbelow(90000000) + 10000000:08d}"
                item = {"desktop_id": identifier, "expires": time.monotonic() + QR_TTL}
                directory_ready = False
                if hub.publisher:
                    await hub.tell(ws, {'type': 'pair_waiting', 'message': '正在準備固定 PWA 配對服務，首次喚醒可能需要約一分鐘'})
                    for _ in range(5):
                        result = await hub.publisher.publish(pin)
                        if result != 'collision':
                            directory_ready = result is True
                            break
                        pin = f"{secrets.randbelow(90000000) + 10000000:08d}"
                    item['expires'] = time.monotonic() + QR_TTL
                hub.qrs[code] = item
                hub.qrs[pin] = item
                qr_url = hub.publisher.pairing_url(code) if hub.publisher else f"{hub.public_url}/?pair={code}"
                await hub.tell(ws, {"type": "qr", "url": qr_url, "relay_url": hub.public_url,
                                    "code": pin, "ttl": QR_TTL, 'directory_ready': directory_ready,
                                    'portable': bool(hub.publisher)})
            elif kind == "pair_decision":
                request_id = p.get("request_id")
                pending = hub.pending.get(request_id)
                if not pending or pending["desktop_id"] != identifier or pending["state"] != "waiting":
                    continue
                if p.get("approve") is True:
                    if hub.desktop_devices(identifier):
                        pending['state'] = 'denied'
                        await hub.tell(ws, {'type': 'pair_locked', 'devices': hub.desktop_devices(identifier)})
                        continue
                    mobile_id = secrets.token_hex(16)
                    token = secrets.token_hex(32)
                    hub.db.execute("INSERT INTO mobiles (id,desktop_id,token_hash,name,created,portable) VALUES (?,?,?,?,?,?)",
                                   (mobile_id, identifier, digest(token), pending["name"], now_iso(), int(pending.get('portable', False))))
                    hub.db.commit()
                    pending["token"] = token
                    pending["state"] = "approved"
                    for code, meta in list(hub.qrs.items()):
                        if meta['desktop_id'] == identifier:
                            hub.qrs.pop(code, None)
                    await hub.update_devices(identifier)
                else:
                    pending["state"] = "denied"
            elif kind == "device_revoke":
                mobile_id = p.get("mobile_id")
                hub.db.execute("DELETE FROM mobiles WHERE id=? AND desktop_id=?", (mobile_id, identifier))
                hub.db.commit()
                for client in list(hub.mobile_sockets.get(mobile_id, set())):
                    await client.close(code=4003, message=b"revoked")
                await hub.update_devices(identifier)
            elif kind in ("chat", "clipboard", "file_start", "file_chunk", "file_end"):
                targets = []
                rows = hub.db.execute("SELECT id FROM mobiles WHERE desktop_id=?", (identifier,))
                for row in rows:
                    targets.extend([m for m in hub.mobile_sockets.get(row["id"], set()) if not m.closed])
                await hub.relay(ws, p, targets, name)
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        await hub.clear_socket_transfers(ws)
        if desktop_id and hub.desktops.get(desktop_id) is ws:
            hub.desktops.pop(desktop_id, None)
            for code, meta in list(hub.qrs.items()):
                if meta["desktop_id"] == desktop_id:
                    hub.qrs.pop(code, None)
            await hub.notify_presence(desktop_id, False)
        await ws.close()
    return ws


async def mobile_socket(request: web.Request):
    hub: Hub = request.app["hub"]
    if not hub.origin_allowed(request):
        raise web.HTTPForbidden()
    auth = hub.mobile_auth(request)
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=135000)
    # Legacy same-origin clients keep their cookie handshake. Fixed-origin PWAs
    # send their token in the first WSS frame, never in a URL or access log.
    if not auth and request.headers.get('Origin') != hub.pwa_origin:
        raise web.HTTPUnauthorized()
    await ws.prepare(request)
    if not auth:
        try:
            first = await ws.receive_json(timeout=10)
            auth = hub.token_auth(first.get('token', '')) if isinstance(first, dict) and first.get('type') == 'mobile_hello' else None
        except (asyncio.TimeoutError, ValueError, TypeError):
            auth = None
        if not auth:
            await ws.close(code=4003, message=b'unauthorized')
            return ws
    mid, did = auth["id"], auth["desktop_id"]
    for previous in list(hub.mobile_sockets.get(mid, set())):
        await previous.close(code=4001, message=b'replaced')
    hub.mobile_sockets.setdefault(mid, set()).add(ws)
    await hub.tell(ws, {"type": "welcome", "name": auth["desktop_name"],
                        "online": did in hub.desktops, "limit_mb": 20})
    await hub.update_devices(did)
    try:
        async for event in ws:
            if event.type != WSMsgType.TEXT:
                continue
            # This device could have been unpaired from the desktop UI.
            if not hub.db.execute("SELECT 1 FROM mobiles WHERE id=?", (mid,)).fetchone():
                break
            try:
                p = json.loads(event.data)
            except (ValueError, TypeError):
                continue
            if not isinstance(p, dict):
                continue
            if p.get("type") in ("chat", "clipboard", "file_start", "file_chunk", "file_end"):
                target = hub.desktops.get(did)
                await hub.relay(ws, p, [target] if target and not target.closed else [], auth["name"])
    finally:
        await hub.clear_socket_transfers(ws)
        hub.mobile_sockets.get(mid, set()).discard(ws)
        await hub.update_devices(did)
        await ws.close()
    return ws


@web.middleware
async def headers(request, handler):
    hub = request.app['hub']
    origin = request.headers.get('Origin')
    if request.path.startswith('/api/') and not hub.origin_allowed(request):
        raise web.HTTPForbidden()
    try:
        response = web.Response(status=204) if request.method == 'OPTIONS' and hub.origin_allowed(request) else await handler(request)
    except web.HTTPException as error:
        response = error
    if origin == hub.pwa_origin:
        response.headers.update({'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
                                 'Access-Control-Allow-Headers': 'Authorization, Content-Type',
                                 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'})
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' blob: data:; connect-src 'self' https: ws: wss:; media-src 'self' blob:; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


def create_app(*, db_path: Path | None = None, public_url: str | None = None,
               enroll_key: str | None = None) -> web.Application:
    base_url = (public_url or os.environ.get("AUREO_PUBLIC_URL") or "http://localhost:8787").rstrip("/")
    if urlsplit(base_url).scheme not in {"http", "https"}:
        raise ValueError("AUREO_PUBLIC_URL must be http(s)")
    key = enroll_key if enroll_key is not None else os.environ.get("AUREO_ENROLL_KEY", "")
    if not key:
        raise ValueError("Set a strong AUREO_ENROLL_KEY (required, even for local tests)")
    database = db_path or Path(os.environ.get("AUREO_DB_PATH", str(ROOT / "data" / "hub.sqlite3")))
    app = web.Application(middlewares=[headers], client_max_size=32 * 1024)
    app["hub"] = Hub(Path(database), base_url, key)
    app.router.add_get("/", index)
    app.router.add_get("/api/me", current_user)
    app.router.add_post("/api/pair/claim", claim)
    app.router.add_get("/api/pair/status", claim_status)
    app.router.add_post("/api/pair/status", claim_status)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/ws/desktop", desktop_socket)
    app.router.add_get("/ws/mobile", mobile_socket)
    app.router.add_route('OPTIONS', '/api/{tail:.*}', current_user)
    def static_handler(fname):
        async def serve_file(request):
            return web.FileResponse(PWA / fname)
        return serve_file
    for path in ("app.css", "app.js", "connection.js", "scanner.js", "sw.js", "manifest.webmanifest"):
        app.router.add_get("/" + path, static_handler(path))
    app.router.add_static("/icons/", PWA / "icons", show_index=False)
    app.router.add_static('/vendor/', PWA / 'vendor', show_index=False)
    async def cleanup(app):
        app["hub"].close()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == "__main__":
    host = os.environ.get("AUREO_HOST", "127.0.0.1")
    port = int(os.environ.get("AUREO_PORT", "8787"))
    print(f"AUREO LINK relay: {host}:{port} (public={os.environ.get('AUREO_PUBLIC_URL','http://localhost:8787')})")
    web.run_app(create_app(), host=host, port=port)
