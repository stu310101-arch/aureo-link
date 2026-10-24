"""Publish expiring addresses. The directory never receives the resume HMAC key."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
from aiohttp import ClientSession, ClientTimeout

PHONE_ENTRY = 'https://stu310101-arch.github.io/aureo-link/phone/'
DIRECTORY_URL = 'https://amos-link-pairing-stu310101.onrender.com'

class Publisher:
    def __init__(self, home: Path, hub, *, url=DIRECTORY_URL):
        self.hub = hub
        self.url = url.rstrip('/')
        file = home / 'phone-identity.json'
        try:
            self.identity = json.loads(file.read_text(encoding='utf-8'))
            assert all(len(self.identity[k]) == 64 for k in ('owner_key', 'route_key'))
            for value in self.identity.values(): bytes.fromhex(value)
        except (OSError, ValueError, KeyError, AssertionError, TypeError):
            self.identity = {k: secrets.token_hex(32) for k in ('owner_key', 'route_key')}
            file.write_text(json.dumps(self.identity), encoding='utf-8')
        self.locator = hashlib.sha256(self.identity['owner_key'].encode()).hexdigest()
        self.lock = asyncio.Lock()
        self.available = False

    def pairing_url(self, token):
        return PHONE_ENTRY + '#' + urlencode({'relay': self.hub.public_url, 'pair': token, 'locator': self.locator})

    def credentials(self):
        return {'locator': self.locator, 'route_key': self.identity['route_key']}

    async def publish(self, pin=None, ttl=90, *, heartbeat=False):
        async with self.lock:
            if heartbeat:
                self.hub.purge_expired()
                active = next(((p, data) for p, data in self.hub.qrs.items() if p.isdigit() and len(p) == 8), None)
                pin = active[0] if active else None
                ttl = active[1]['expires'] - time.monotonic() if active else 90
            expires = int(time.time()) + 180
            message = f'{self.locator}\n{self.hub.public_url}\n{expires}'
            proof = hmac.new(bytes.fromhex(self.identity['route_key']), message.encode(), hashlib.sha256).hexdigest()
            data = {'owner_key': self.identity['owner_key'], 'url': self.hub.public_url, 'expires': expires, 'proof': proof}
            if pin:
                data.update(pin=pin, pin_ttl=max(1, min(90, int(ttl))))
            try:
                async with ClientSession(timeout=ClientTimeout(total=80)) as client:
                    async with client.post(self.url + '/v1/announce', json=data) as response:
                        if response.status == 409:
                            return 'collision'
                        self.available = response.status == 200
                        return self.available
            except (OSError, asyncio.TimeoutError):
                self.available = False
                return False

    async def run(self):
        while True:
            await self.publish(heartbeat=True)
            await asyncio.sleep(30)
