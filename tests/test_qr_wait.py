from types import SimpleNamespace
from desktop.app import Desktop

def test_countdown_keeps_one_request_while_directory_is_waking():
    desktop=Desktop.__new__(Desktop)
    desktop.qr_requested=False;desktop.qr_expiry=0
    desktop.online=True;desktop.devices=[];desktop.pairing_pending=False
    packets=[]
    desktop.send=lambda item:packets.append(item) or True
    desktop.qr_label=SimpleNamespace(configure=lambda **kw:None)
    desktop.countdown_var=SimpleNamespace(set=lambda value:None)
    desktop.root=SimpleNamespace(after=lambda *args:None)
    for _ in range(80):desktop.countdown()
    assert packets==[{'type':'new_qr'}]
    desktop.qr_requested=False
    desktop.countdown()
    assert len(packets)==2
