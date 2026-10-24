import hashlib
import secrets
import time
import pytest
from aiohttp.test_utils import TestClient, TestServer
from directory.app import create_app, PHONE_ORIGIN

def announcement(**overrides):
    return dict(owner_key=secrets.token_hex(32), url='https://synthetic-test.trycloudflare.com',
                proof=secrets.token_hex(32), expires=int(time.time())+180, pin='12345678', **overrides)

@pytest.mark.asyncio
async def test_directory_code_and_route_lease_survive_client_renewal():
    async with TestClient(TestServer(create_app())) as client:
        data=announcement()
        res=await client.post('/v1/announce',json=data)
        assert res.status==200
        locator=(await res.json())['locator']
        assert locator==hashlib.sha256(data['owner_key'].encode()).hexdigest()
        res=await client.get('/v1/pins/12345678',headers={'Origin':PHONE_ORIGIN})
        assert res.status==200 and res.headers['Access-Control-Allow-Origin']==PHONE_ORIGIN
        result=await res.json()
        assert result['url']==data['url'] and 'owner_key' not in result
        data['url']='https://new-address.trycloudflare.com'
        data.pop('pin')
        assert (await client.post('/v1/announce',json=data)).status==200
        assert (await client.get('/v1/pins/12345678')).status==404
        assert (await (await client.get('/v1/devices/'+locator)).json())['url']==data['url']

@pytest.mark.asyncio
async def test_directory_collision_and_hostile_origins():
    async with TestClient(TestServer(create_app())) as client:
        data=announcement()
        assert (await client.post('/v1/announce',json=data)).status==200
        assert (await client.post('/v1/announce',json=announcement())).status==409
        assert (await client.get('/v1/pins/12345678',headers={'Origin':'https://evil.invalid'})).status==403
        assert (await client.post('/v1/announce',json=dict(data,url='http://127.0.0.1'))).status==400
        assert (await client.post('/v1/announce',json=dict(data,url='https://example.com'))).status==400
        assert (await client.post('/v1/announce',json=dict(data,url='https://a.trycloudflare.com:bad'))).status==400
        assert (await client.post('/v1/announce',json=dict(data,expires=int(time.time())-1))).status==400

@pytest.mark.asyncio
async def test_directory_forgetful_restart_can_be_repopulated_without_account():
    data=announcement()
    for _ in range(2):
        async with TestClient(TestServer(create_app())) as client:
            assert (await client.get('/v1/pins/12345678')).status==404
            assert (await client.post('/v1/announce',json=data)).status==200
            assert (await client.get('/v1/pins/12345678')).status==200

@pytest.mark.asyncio
async def test_heartbeat_reads_current_pin_after_waiting_for_registration_lock(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from server.directory_client import Publisher
    hub=SimpleNamespace(public_url='https://test-heartbeat.trycloudflare.com',qrs={},purge_expired=lambda:None)
    async with TestClient(TestServer(create_app())) as client:
        publisher=Publisher(tmp_path,hub,url=str(client.make_url('')).rstrip('/'))
        await publisher.lock.acquire()
        task=asyncio.create_task(publisher.publish(heartbeat=True))
        await asyncio.sleep(0)
        hub.qrs['12345678']={'expires':time.monotonic()+90}
        publisher.lock.release()
        assert await task is True
        assert (await client.get('/v1/pins/12345678')).status==200
