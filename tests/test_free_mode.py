import asyncio
import queue
import secrets

from aiohttp import ClientSession
import pytest

from desktop.free_mode import FreeRelay


@pytest.mark.asyncio
async def test_free_relay_starts_authenticates_and_stops(tmp_path, monkeypatch):
    class Process:
        returncode = None

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b'Quick tunnel https://aureo-test.trycloudflare.com\n')
            self.stdout.feed_data(b'Registered tunnel connection connIndex=0\n')

        def terminate(self):
            self.returncode = 0
            self.stdout.feed_eof()

        async def wait(self):
            return self.returncode

    process = Process()

    async def spawn(*args, **kwargs):
        assert '--url' in args
        assert kwargs['stderr'] == asyncio.subprocess.STDOUT
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    async def publish(self, pin=None, ttl=90, **kwargs):
        return True
    monkeypatch.setattr('server.directory_client.Publisher.publish', publish)
    executable = tmp_path / 'cloudflared.exe'
    executable.touch()
    events = queue.Queue()
    relay = FreeRelay(tmp_path / 'profile', events, 7, tunnel_path=executable)
    task = asyncio.create_task(relay.serve())
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            packets = []
            while not events.empty():
                token, packet = events.get_nowait()
                assert token == 7
                packets.append(packet)
            ready = next((item for item in packets if item['type'] == 'free_ready'), None)
            if ready:
                break
        else:
            pytest.fail('free relay never became ready')
        async with ClientSession() as client:
            ws = await client.ws_connect(ready['server_url'])
            await ws.send_json({'type': 'desktop_hello', 'desktop_id': secrets.token_hex(16),
                                'secret': secrets.token_hex(32), 'enroll_key': ready['enroll_key']})
            assert (await ws.receive_json(timeout=3))['type'] == 'desktop_welcome'
            await ws.send_json({'type': 'new_qr'})
            qr = await ws.receive_json(timeout=3)
            assert qr['type']=='pair_waiting'
            qr = await ws.receive_json(timeout=3)
            assert qr['url'].startswith('https://stu310101-arch.github.io/aureo-link/phone/#relay=')
            assert qr['relay_url']=='https://aureo-test.trycloudflare.com'
            assert qr['directory_ready'] is True
            await ws.close()
    finally:
        relay.stop()
        await asyncio.wait_for(task, 5)
    assert process.returncode == 0
    assert (tmp_path / 'profile' / 'free-relay.sqlite3').exists()
