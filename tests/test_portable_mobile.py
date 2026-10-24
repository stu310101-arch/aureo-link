import secrets
import pytest
from aiohttp.test_utils import TestClient, TestServer
from server.app import create_app
from server.directory_client import Publisher, PHONE_ENTRY

ORIGIN='https://stu310101-arch.github.io'

async def packet(ws, kind):
    for _ in range(12):
        item=await ws.receive_json(timeout=3)
        if item['type']==kind:return item
    raise AssertionError('missing '+kind)

@pytest.mark.asyncio
async def test_fixed_pwa_token_survives_new_browser_and_changed_tunnel(tmp_path,monkeypatch):
    async def publish(self,pin=None,ttl=90,**kwargs):return True
    monkeypatch.setattr(Publisher,'publish',publish)
    did,secret=secrets.token_hex(16),secrets.token_hex(32)
    database=tmp_path/'hub.sqlite'
    token=None;locator=None;route_key=None
    for iteration in range(2):
        public=f'https://session-{iteration}.trycloudflare.com'
        app=create_app(db_path=database,public_url=public,enroll_key='test-enroll')
        app['hub'].publisher=Publisher(tmp_path,app['hub'])
        async with TestClient(TestServer(app)) as client:
            desktop=await client.ws_connect('/ws/desktop')
            await desktop.send_json({'type':'desktop_hello','desktop_id':did,'secret':secret,'enroll_key':'test-enroll'})
            welcome=await packet(desktop,'desktop_welcome')
            if iteration==0:
                await desktop.send_json({'type':'new_qr'})
                qr=await packet(desktop,'qr')
                assert qr['url'].startswith(PHONE_ENTRY+'#relay=')
                assert qr['directory_ready'] is True
                response=await client.post('/api/pair/claim',headers={'Origin':ORIGIN},json={'code':qr['code'],'name':'Synthetic PWA'})
                claim=await response.json()
                pending=await packet(desktop,'pair_request')
                await desktop.send_json({'type':'pair_decision','request_id':pending['request_id'],'approve':True})
                await packet(desktop,'devices')
                response=await client.post('/api/pair/status',headers={'Origin':ORIGIN},json=claim)
                result=await response.json()
                assert result['status']=='approved' and len(result['token'])==64
                assert response.headers['Access-Control-Allow-Origin']==ORIGIN
                token,locator,route_key=result['token'],result['locator'],result['route_key']
                assert token not in qr['url'] and route_key not in qr['url']
            else:
                assert len(welcome['devices'])==1,'a new process must keep its portable device slot'
                assert app['hub'].publisher.credentials()=={'locator':locator,'route_key':route_key}
                assert not client.session.cookie_jar,'this is a fresh browser without old cookies'
                await desktop.send_json({'type':'new_qr'})
                assert (await packet(desktop,'pair_locked'))['devices']
            headers={'Origin':ORIGIN,'Authorization':'Bearer '+token}
            user=await (await client.get('/api/me',headers=headers)).json()
            assert user['paired'] and user['desktop_id']==did
            assert (await client.get('/api/me',headers=dict(headers,Origin='https://evil.invalid'))).status==403
            preflight=await client.options('/api/me',headers={'Origin':ORIGIN,'Access-Control-Request-Headers':'authorization'})
            assert preflight.status==204 and preflight.headers['Access-Control-Allow-Origin']==ORIGIN
            mobile=await client.ws_connect('/ws/mobile',headers={'Origin':ORIGIN})
            await mobile.send_json({'type':'mobile_hello','token':token})
            assert (await packet(mobile,'welcome'))['online']
            await mobile.send_json({'type':'chat','text':'reopened app works','client_id':'synthetic'})
            assert (await packet(desktop,'chat'))['text']=='reopened app works'
            await desktop.send_json({'type':'clipboard','text':'clipboard after restart','client_id':'synthetic2'})
            assert (await packet(mobile,'clipboard'))['text']=='clipboard after restart'
            await mobile.close();await desktop.close()

@pytest.mark.asyncio
async def test_fixed_pwa_ws_rejects_malformed_token_without_cookie(tmp_path):
    app=create_app(db_path=tmp_path/'hub.sqlite',public_url='https://test.trycloudflare.com',enroll_key='key')
    async with TestClient(TestServer(app)) as client:
        mobile=await client.ws_connect('/ws/mobile',headers={'Origin':ORIGIN})
        await mobile.send_json({'type':'mobile_hello','token':42})
        await mobile.receive(timeout=3)
        assert mobile.close_code==4003
