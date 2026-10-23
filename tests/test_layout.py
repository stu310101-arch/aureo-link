"""Verify the minimum desktop window leaves the main controls visible."""
from tkinter import Button, TclError, Toplevel

import pytest

from desktop import app


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def assert_inside(widget, window):
    x = widget.winfo_rootx() - window.winfo_rootx()
    y = widget.winfo_rooty() - window.winfo_rooty()
    assert widget.winfo_ismapped(), widget.cget('text')
    assert widget.winfo_height() >= widget.winfo_reqheight(), widget.cget('text')
    assert 0 <= x and x + widget.winfo_width() <= window.winfo_width(), widget.cget('text')
    assert 0 <= y and y + widget.winfo_height() <= window.winfo_height(), widget.cget('text')


def test_main_and_settings_controls_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'CONFIG_HOME', tmp_path)
    monkeypatch.setattr(app, 'CONFIG_FILE', tmp_path / 'settings.json')
    monkeypatch.setattr(app, 'HISTORY_FILE', tmp_path / 'history.json')
    monkeypatch.setattr(app.Desktop, 'start_free_mode', lambda self: None)
    try:
        desktop = app.Desktop()
    except TclError as error:
        if 'display' in str(error).lower():
            pytest.skip('Tk requires a display')
        raise
    try:
        desktop.root.geometry('1000x800')
        desktop.root.update_idletasks()
        buttons = {widget.cget('text'): widget for widget in descendants(desktop.root)
                   if isinstance(widget, Button)}
        for label in ('選擇', '傳檔案', '貼上傳送', '傳送 →', '移除選取裝置', '同步目前剪貼簿', '開啟', '複製'):
            assert_inside(buttons[label], desktop.root)
        desktop.connection_dialog()
        desktop.root.update()
        dialog = next(widget for widget in desktop.root.winfo_children()
                      if isinstance(widget, Toplevel))
        confirm = next(widget for widget in descendants(dialog)
                       if isinstance(widget, Button) and widget.cget('text') == '儲存設定並連線 →')
        assert_inside(confirm, dialog)
    finally:
        desktop.stop_event.set()
        desktop.root.destroy()
