"""Free, stateless-across-restarts rendezvous; PCs renew signed address leases."""
from __future__ import annotations
import hashlib
import os
import re
import time
from urllib.parse import urlsplit
from aiohttp import web

PHONE_ORIGIN = 'https://stu310101-arch.github.io'
HEX = re.compile(r'^[a-f0-9]{64}$')

class Directory:
    def __init__(self):
        self.devices = {}
        self.pins = {}
        self.attempts = {}

    def purge(self):
        now = time.time()
        self.devices = {k: v for k, v in self.devices.items() if v['expires'] > now}
        self.pins = {k: v for k, v in self.pins.items() if v[1] > now and v[0] in self.devices}
        self.attempts = {k: [t for t in v if t > now - 60] for k, v in self.attempts.items() if any(t > now - 60 for t in v)}

    def limit(self, key, count):
        self.purge()
        stamps = self.attempts.setdefault(key, [])
        if len(stamps) >= count:
            raise web.HTTPTooManyRequests(text='Please wait before retrying')
        stamps.append(time.time())

@web.middleware
async def headers(request, handler):
    origin = request.headers.get('Origin')
    if origin and origin != PHONE_ORIGIN:
        raise web.HTTPForbidden()
    try:
        response = web.Response(status=204) if request.method == 'OPTIONS' else await handler(request)
    except web.HTTPException as error:
        response = error
    response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})
    if origin:
        response.headers.update({'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
                                 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                                 'Access-Control-Allow-Headers': 'Content-Type'})
    return response

async def health(request):
    return web.json_response({'ok': True, 'service': 'Amos LINK pairing directory', 'version': '3.0.0'})

async def announce(request):
    directory = request.app['directory']
    directory.limit(('announce', request.remote), 150)
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest()
    if not isinstance(data, dict):
        raise web.HTTPBadRequest()
    owner = data.get('owner_key', '')
    proof = data.get('proof', '')
    url = data.get('url', '')
    expires = data.get('expires')
    if not isinstance(owner, str) or not HEX.fullmatch(owner) or not isinstance(proof, str) or not HEX.fullmatch(proof):
        raise web.HTTPBadRequest(text='Invalid lease credentials')
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if parsed: parsed.port
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid address')
    if not parsed or parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.path or parsed.query or parsed.fragment or not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com', parsed.hostname or ''):
        raise web.HTTPBadRequest(text='Expected a Cloudflare Quick Tunnel origin')
    if not isinstance(expires, int) or not time.time() + 5 < expires <= time.time() + 300:
        raise web.HTTPBadRequest(text='Invalid lease expiry')
    locator = hashlib.sha256(owner.encode()).hexdigest()
    directory.limit(('owner', locator), 30)
    if locator not in directory.devices and len(directory.devices) >= 10000:
        raise web.HTTPServiceUnavailable(text='Directory busy')
    pin = data.get('pin')
    ttl = data.get('pin_ttl', 90)
    if pin is not None:
        if not isinstance(pin, str) or not re.fullmatch(r'\d{8}', pin) or not isinstance(ttl, int) or not 1 <= ttl <= 90:
            raise web.HTTPBadRequest(text='Invalid pairing code')
        occupied = directory.pins.get(pin)
        if occupied and occupied[0] != locator:
            raise web.HTTPConflict(text='Pairing code collision')
    directory.devices[locator] = {'locator': locator, 'url': url, 'proof': proof, 'expires': expires}
    directory.pins = {k: v for k, v in directory.pins.items() if v[0] != locator}
    if pin:
        directory.pins[pin] = (locator, time.time() + ttl)
    return web.json_response({'ok': True, 'locator': locator})

async def resolve_pin(request):
    directory = request.app['directory']
    directory.limit(('pin', request.remote), 15)
    pin = request.match_info['pin']
    if not re.fullmatch(r'\d{8}', pin):
        raise web.HTTPBadRequest()
    item = directory.pins.get(pin)
    if not item:
        raise web.HTTPNotFound(text='Code expired or computer offline')
    return web.json_response(dict(directory.devices[item[0]], pin=pin))

async def resolve_device(request):
    directory = request.app['directory']
    directory.limit(('resolve', request.remote), 180)
    locator = request.match_info['locator']
    if not HEX.fullmatch(locator):
        raise web.HTTPBadRequest()
    entry = directory.devices.get(locator)
    if not entry:
        raise web.HTTPNotFound(text='Computer offline; waiting for its address renewal')
    return web.json_response(entry)

def create_app():
    app = web.Application(middlewares=[headers], client_max_size=4096)
    app['directory'] = Directory()
    app.router.add_get('/health', health)
    app.router.add_post('/v1/announce', announce)
    app.router.add_get('/v1/pins/{pin}', resolve_pin)
    app.router.add_get('/v1/devices/{locator}', resolve_device)
    app.router.add_route('OPTIONS', '/{path:.*}', health)
    return app

if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), access_log=None)
