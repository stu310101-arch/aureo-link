"""Desktop receive-path regression tests without opening a GUI."""
import base64
from pathlib import Path

import pytest

from desktop.app import Desktop, safe_filename


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.mark.parametrize("name, expected", [
    ("../../photo.png", "photo.png"), ("CON.txt", "_CON.txt"),
    ("lpt9", "_lpt9"), ("NUL", "_NUL"), ("hello.txt", "hello.txt"),
])
def test_windows_filename(name, expected):
    from server.app import safe_filename as relay_filename
    assert safe_filename(name) == relay_filename(name) == expected


def receiver(folder):
    desktop = Desktop.__new__(Desktop)
    desktop.folder_var = Value(str(folder))
    desktop.incoming = {}
    desktop.transfer_items = {}
    desktop.failed_transfers = set()
    desktop.transfer_var = Value('')
    desktop.transfer_percent = Value(0)
    desktop.messages = []
    desktop.show_chat = lambda *args, **kwargs: desktop.messages.append(args)
    return desktop


def test_receive_preserves_existing_files_and_discards_incomplete(tmp_path):
    (tmp_path / "note.txt").write_bytes(b"existing")
    desktop = receiver(tmp_path)
    desktop.handle({"type": "file_start", "id": "file1", "name": "../note.txt", "size": 3})
    desktop.handle({"type": "file_chunk", "id": "file1", "seq": 0,
                    "data": base64.b64encode(b"new").decode()})
    desktop.handle({"type": "file_end", "id": "file1"})
    assert (tmp_path / "note.txt").read_bytes() == b"existing"
    assert (tmp_path / "note (1).txt").read_bytes() == b"new"
    desktop.handle({"type": "file_start", "id": "file2", "name": "partial", "size": 3})
    desktop.handle({"type": "file_end", "id": "file2"})
    assert not (tmp_path / "partial").exists()
    assert not list(tmp_path.glob("*.part"))


def test_unwritable_receive_directory_does_not_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_bytes(b"not a folder")
    desktop = receiver(blocker / "child")
    desktop.handle({"type": "file_start", "id": "file1", "name": "data", "size": 1})
    assert not desktop.incoming
    assert "無法準備儲存檔案" in desktop.messages[0][1]


def test_oversized_text_is_not_sent():
    desktop = receiver(Path("unused"))
    desktop.message_var = Value("x" * 12001)
    desktop.send = lambda packet: pytest.fail("oversized text must not reach the socket")
    desktop.send_text()
    assert "12,000" in desktop.messages[0][1]


def test_receive_progress_and_completion(tmp_path):
    desktop = receiver(tmp_path)
    desktop.handle({'type': 'file_start', 'id': 'progress', 'name': 'test.bin', 'size': 6})
    desktop.handle({'type': 'file_chunk', 'id': 'progress', 'seq': 0, 'data': 'YWJj'})
    assert desktop.transfer_percent.get() == 50
    assert '正在接收' in desktop.transfer_var.get()
    desktop.handle({'type': 'file_chunk', 'id': 'progress', 'seq': 1, 'data': 'ZGVm'})
    desktop.handle({'type': 'file_end', 'id': 'progress'})
    assert desktop.transfer_percent.get() == 100
    assert '接收完成' in desktop.transfer_var.get()
    assert not desktop.transfer_items


def test_clipboard_initial_baseline_auto_send_receive_and_no_echo(tmp_path):
    class Root:
        value = 'existing clipboard must not be uploaded on pairing'

        def clipboard_get(self):
            return self.value

        def clipboard_clear(self):
            self.value = ''

        def clipboard_append(self, text):
            self.value += text

        def after(self, *args):
            pass

    import threading
    desktop = receiver(tmp_path)
    desktop.root = Root()
    desktop.online = True
    desktop.devices = [{'online': True}]
    desktop.clipboard_enabled = Value(True)
    desktop.clipboard_var = Value('')
    desktop.clipboard_was_ready = False
    desktop.last_clipboard = None
    desktop.stop_event = threading.Event()
    packets = []
    desktop.send = lambda p: packets.append(p) or True
    desktop.poll_clipboard()
    assert not packets
    desktop.root.value = 'new text copied on PC'
    desktop.poll_clipboard()
    assert packets[-1]['type'] == 'clipboard'
    assert packets[-1]['text'] == 'new text copied on PC'
    desktop.handle({'type': 'clipboard', 'text': 'copied on phone'})
    assert desktop.root.value == 'copied on phone'
    desktop.poll_clipboard()
    assert len(packets) == 1  # receiving must never echo back
    desktop.clipboard_enabled.set(False)
    desktop.handle({'type': 'clipboard', 'text': 'disabled'})
    assert desktop.root.value == 'copied on phone'


def test_countdown_never_requests_qr_while_paired(tmp_path):
    desktop = receiver(tmp_path)
    desktop.online = True
    desktop.devices = [{'online': True}]
    desktop.pairing_pending = False
    desktop.root = type('Root', (), {'after': lambda *args: None})()
    desktop.send = lambda p: pytest.fail('QR must stop after pairing')
    desktop.countdown()


def test_send_confirmation_and_error_remove_transfer(tmp_path):
    desktop = receiver(tmp_path)
    desktop.update_transfer('test', 'photo.png', 2, 4, 'send')
    assert desktop.transfer_percent.get() == 50
    desktop.handle({'type': 'sent', 'id': 'test'})
    assert not desktop.transfer_items
    assert '已送出' in desktop.transfer_var.get()
    desktop.update_transfer('test2', 'large.bin', 2, 4, 'send')
    desktop.handle({'type': 'error', 'id': 'test2', 'message': '對方已離線'})
    assert not desktop.transfer_items
    assert desktop.transfer_percent.get() == 0
