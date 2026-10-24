"""Protocol tests: first pairing, persistent authentication, text, file, revoke."""
import base64
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from server.app import MAX_FILE_BYTES, create_app, safe_filename


@pytest.mark.asyncio
async def test_malformed_json_does_not_break_connection(tmp_path):
    app = create_app(db_path=tmp_path / 'hub.sqlite',
                     public_url='http://127.0.0.1:8787', enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        for value in ([], None, 'text', 123):
            response = await client.post('/api/pair/claim', json=value)
            assert response.status == 400
        ws = await client.ws_connect('/ws/desktop')
        await ws.send_json({'type': 'desktop_hello', 'desktop_id': secrets.token_hex(16),
                            'secret': secrets.token_hex(32), 'enroll_key': 'key'})
        assert (await ws.receive_json(timeout=3))['type'] == 'desktop_welcome'
        for value in ([], None, 'text', 123):
            await ws.send_json(value)
        await ws.send_json({'type': 'new_qr'})
        assert (await ws.receive_json(timeout=3))['type'] == 'qr'
        await ws.close()


@pytest.mark.asyncio
async def test_end_to_end(tmp_path: Path):
    app = create_app(db_path=tmp_path / "hub.sqlite", public_url="http://127.0.0.1:8787",
                     enroll_key="my-private-enrollment")
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        mid = secrets.token_hex(16)
        secret = secrets.token_hex(32)
        desktop = await client.ws_connect('/ws/desktop')
        await desktop.send_json({"type": "desktop_hello", "desktop_id": mid, "secret": secret,
                                 "name": "My Desktop", "enroll_key": "my-private-enrollment"})
        welcome = await desktop.receive_json(timeout=3)
        assert welcome['type'] == 'desktop_welcome'
        assert welcome['devices'] == []

        await desktop.send_json({"type": "new_qr"})
        qr = await desktop.receive_json(timeout=3)
        assert qr['type'] == 'qr'
        pin = qr['code']
        assert len(pin) == 8 and pin.isnumeric()
        link = parse_qs(urlsplit(qr['url']).query)['pair'][0]
        assert len(link) == 48

        claim = await client.post('/api/pair/claim', json={'code': pin, 'name': 'My iPhone'})
        assert claim.status == 200
        ticket = await claim.json()
        assert ticket['status'] == 'waiting'
        request = await desktop.receive_json(timeout=3)
        assert request['type'] == 'pair_request' and request['name'] == 'My iPhone'

        # Both the short PIN and QR URL are one-use aliases.
        duplicate = await client.post('/api/pair/claim', json={'code': link, 'name': 'Untrusted'})
        assert duplicate.status == 410

        await desktop.send_json({'type': 'pair_decision', 'request_id': request['request_id'], 'approve': True})
        devices = await desktop.receive_json(timeout=3)
        assert devices['type'] == 'devices' and len(devices['devices']) == 1

        status = await client.get('/api/pair/status', params={'request_id': ticket['request_id'],
                                                             'proof': ticket['proof']})
        assert (await status.json())['status'] == 'approved'
        assert 'httponly' in status.headers['Set-Cookie'].lower()
        me = await client.get('/api/me')
        assert (await me.json())['paired'] is True

        mobile = await client.ws_connect('/ws/mobile', headers={'Origin': 'http://127.0.0.1:8787'})
        phone_welcome = await mobile.receive_json(timeout=3)
        assert phone_welcome['type'] == 'welcome' and phone_welcome['online'] is True
        devices = await desktop.receive_json(timeout=3)
        assert devices['type'] == 'devices' and devices['devices'][0]['online'] is True

        # Pairing is locked at the server, including explicit QR renewal requests.
        await desktop.send_json({'type': 'new_qr'})
        locked = await desktop.receive_json(timeout=3)
        assert locked['type'] == 'pair_locked'
        assert not app['hub'].qrs
        app['hub'].qrs['87654321'] = {'desktop_id': mid, 'expires': time.monotonic() + 30}
        intruder = await client.post('/api/pair/claim', json={'code': '87654321', 'name': 'Second phone'})
        assert intruder.status == 409
        assert len(app['hub'].desktop_devices(mid)) == 1

        await mobile.send_json({'type': 'clipboard', 'text': '手機複製的文字'})
        clipboard = await desktop.receive_json(timeout=3)
        assert clipboard['type'] == 'clipboard' and clipboard['text'] == '手機複製的文字'
        assert (await mobile.receive_json(timeout=3))['type'] == 'sent'
        await desktop.send_json({'type': 'clipboard', 'text': '電腦複製的文字'})
        assert (await mobile.receive_json(timeout=3))['text'] == '電腦複製的文字'
        assert (await desktop.receive_json(timeout=3))['type'] == 'sent'

        # Malformed JSON values must not tear down an authenticated socket.
        for value in ([], None, 'text', 123):
            await mobile.send_json(value)

        await mobile.send_json({'type': 'chat', 'text': '你好，電腦！'})
        chat = await desktop.receive_json(timeout=3)
        assert chat['type'] == 'chat' and chat['text'] == '你好，電腦！'
        sent = await mobile.receive_json(timeout=3)
        assert sent['type'] == 'sent'
        await desktop.send_json({'type': 'chat', 'text': '從電腦傳送網址 https://example.com'})
        reply = await mobile.receive_json(timeout=3)
        assert reply['type'] == 'chat'
        await desktop.receive_json(timeout=3)  # sent ack

        payload = b'hello world' * 55
        fid = secrets.token_hex(12)
        await mobile.send_json({'type': 'file_start', 'id': fid, 'name': '../image.png',
                                'size': len(payload), 'mime': 'image/png'})
        start = await desktop.receive_json(timeout=3)
        assert start['type'] == 'file_start' and start['name'] == 'image.png'
        await mobile.send_json({'type': 'file_chunk', 'id': fid, 'seq': 0,
                                'data': base64.b64encode(payload).decode()})
        chunk = await desktop.receive_json(timeout=3)
        assert base64.b64decode(chunk['data']) == payload
        await mobile.send_json({'type': 'file_end', 'id': fid})
        assert (await desktop.receive_json(timeout=3))['type'] == 'file_end'
        assert (await mobile.receive_json(timeout=3))['type'] == 'sent'

        await mobile.send_json({'type': 'file_start', 'id': secrets.token_hex(12),
                                'name': 'too-large', 'size': MAX_FILE_BYTES + 1})
        bad = await mobile.receive_json(timeout=3)
        assert bad['type'] == 'error' and bad['id']

        # Device revocation permanently disables previous cookie.
        await desktop.send_json({'type': 'device_revoke', 'mobile_id': devices['devices'][0]['id']})
        await mobile.receive(timeout=3)
        assert (await desktop.receive_json(timeout=3))['type'] == 'devices'
        await desktop.send_json({'type': 'new_qr'})
        for _ in range(3):
            renewed = await desktop.receive_json(timeout=3)
            if renewed['type'] == 'qr':
                break
            assert renewed['type'] == 'devices'
        assert renewed['type'] == 'qr'
        me = await client.get('/api/me')
        assert (await me.json())['paired'] is False
        await desktop.close()
        await mobile.close()


@pytest.mark.asyncio
async def test_pair_denied_and_invalid_origin(tmp_path: Path):
    app = create_app(db_path=tmp_path / 'test.db', public_url='http://127.0.0.1:8787',
                     enroll_key='test-enroll')
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        unauthorized = await client.get('/ws/mobile')
        assert unauthorized.status == 401
        bad_origin = await client.post('/api/pair/claim', json={'code': '12345678'},
                                       headers={'Origin': 'https://untrusted.site'})
        assert bad_origin.status == 403
        did, secret = secrets.token_hex(16), secrets.token_hex(32)
        desk = await client.ws_connect('/ws/desktop')
        await desk.send_json({'type': 'desktop_hello', 'desktop_id': did, 'secret': secret,
                              'enroll_key': 'wrong'})
        assert (await desk.receive_json(timeout=3))['type'] == 'error'
        await desk.close()
        assert safe_filename('../../evil.exe') == 'evil.exe'


@pytest.mark.asyncio
async def test_registration_persists_after_reconnect(tmp_path: Path):
    app = create_app(db_path=tmp_path / 'hub.sqlite', public_url='http://127.0.0.1:8787', enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        did, secret = secrets.token_hex(16), secrets.token_hex(32)
        for key in ('key', 'not-required-after-first-enrollment'):
            ws = await client.ws_connect('/ws/desktop')
            await ws.send_json({'type': 'desktop_hello', 'desktop_id': did,
                                'secret': secret, 'enroll_key': key})
            assert (await ws.receive_json(timeout=3))['type'] == 'desktop_welcome'
            await ws.close()


@pytest.mark.asyncio
async def test_pair_denial_and_expiry(tmp_path):
    app = create_app(db_path=tmp_path / 'hub.sqlite',
                     public_url='http://127.0.0.1:8787', enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        ws = await client.ws_connect('/ws/desktop')
        await ws.send_json({'type': 'desktop_hello', 'desktop_id': secrets.token_hex(16),
                            'secret': secrets.token_hex(32), 'enroll_key': 'key'})
        await ws.receive_json(timeout=3)
        await ws.send_json({'type': 'new_qr'})
        qr = await ws.receive_json(timeout=3)
        response = await client.post('/api/pair/claim', json={'code': qr['code']})
        ticket = await response.json()
        request = await ws.receive_json(timeout=3)
        await ws.send_json({'type': 'new_qr'})
        assert (await ws.receive_json(timeout=3))['type'] == 'pair_waiting'
        await ws.send_json({'type': 'pair_decision', 'request_id': request['request_id'],
                            'approve': False})
        await ws.send_json({'type': 'new_qr'})
        qr = await ws.receive_json(timeout=3)  # processing barrier after denial
        status = await client.get('/api/pair/status', params={
            'request_id': ticket['request_id'], 'proof': ticket['proof']})
        assert (await status.json())['status'] == 'denied'
        assert not (await (await client.get('/api/me')).json())['paired']
        for item in app['hub'].qrs.values():
            item['expires'] = 0
        expired = await client.post('/api/pair/claim', json={'code': qr['code']})
        assert expired.status == 410
        await ws.close()


@pytest.mark.asyncio
async def test_pwa_shell_assets(tmp_path):
    app = create_app(db_path=tmp_path / 'hub.sqlite',
                     public_url='http://127.0.0.1:8787', enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        for path in ('/', '/app.js', '/app.css', '/sw.js', '/manifest.webmanifest',
                     '/icons/icon-192.png', '/icons/icon-512.png'):
            response = await client.get(path)
            assert response.status == 200, path
            assert len(await response.read()) > 0
            assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.asyncio
async def test_receiver_disconnect_reports_failed_transfer(tmp_path):
    from server.app import digest, now_iso
    app = create_app(db_path=tmp_path / 'hub.sqlite', public_url='http://127.0.0.1:8787', enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        did, secret, token = secrets.token_hex(16), secrets.token_hex(32), secrets.token_hex(32)
        desktop = await client.ws_connect('/ws/desktop')
        await desktop.send_json({'type':'desktop_hello', 'desktop_id':did, 'secret':secret, 'enroll_key':'key'})
        await desktop.receive_json(timeout=3)
        app['hub'].db.execute('INSERT INTO mobiles (id,desktop_id,token_hash,name,created) VALUES (?,?,?,?,?)',
                             (secrets.token_hex(16), did, digest(token), 'Phone', now_iso()))
        app['hub'].db.commit()
        mobile = await client.ws_connect('/ws/mobile', headers={'Cookie': 'aureo_session=' + token})
        await mobile.receive_json(timeout=3)
        await desktop.receive_json(timeout=3)
        await desktop.send_json({'type':'file_start', 'id':'interrupted', 'size':100, 'name':'test.bin'})
        assert (await mobile.receive_json(timeout=3))['type'] == 'file_start'
        await mobile.close()
        error = await desktop.receive_json(timeout=3)
        assert error['type'] == 'error' and error['id'] == 'interrupted'
        assert not app['hub'].transfers
        await desktop.close()
