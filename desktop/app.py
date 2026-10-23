"""AUREO LINK Windows desktop companion (Tkinter / dark-gold UI)."""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import secrets
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import Tk, Toplevel, Frame, Label, Button, Checkbutton, Entry, StringVar, BooleanVar, DoubleVar, END, Text, Listbox, filedialog, messagebox, ttk

import qrcode
import websocket
from PIL import Image, ImageTk, ImageGrab

RESOURCE_ROOT = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
if str(RESOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(RESOURCE_ROOT))
from desktop.free_mode import FreeRelay

APP = "AUREO LINK"
BG = "#0E0E11"
PANEL = "#17171B"
CARD = "#212126"
BORDER = "#36332E"
GOLD = "#DCB77B"
GOLD_HI = "#EBC994"
TEXT = "#EEECE8"
MUTED = "#96918C"
GREEN = "#74C7A1"
MAX_FILE = 20 * 1024 * 1024
CHUNK = 48 * 1024
CONFIG_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AureoLink"
CONFIG_FILE = CONFIG_HOME / "settings.json"
HISTORY_FILE = CONFIG_HOME / "history.json"


def ensure_home():
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)


def save_json(path, value):
    ensure_home()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return fallback


def base_settings():
    return {
        "desktop_id": secrets.token_hex(16),
        "secret": secrets.token_hex(32),
        "server_url": "ws://127.0.0.1:8787/ws/desktop",
        "save_folder": str(Path.home() / "Downloads" / "AureoLink"),
        "name": socket.gethostname()[:35] or "Windows 電腦",
        "mode": "free",
    }


def safe_filename(name):
    name = str(name or "file").replace("\\", "/").split("/")[-1]
    name = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name)
    name = name.strip(". ")[:145].rstrip(". ") or "file"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


class Desktop:
    def __init__(self):
        self.config = load_json(CONFIG_FILE, None)
        first_run = not isinstance(self.config, dict) or not self.config.get("secret")
        if first_run:
            self.config = base_settings()
            save_json(CONFIG_FILE, self.config)
        if '--free' in sys.argv:
            self.config['mode'] = 'free'
        self.history = load_json(HISTORY_FILE, [])
        if not isinstance(self.history, list):
            self.history = []
        self.ws = None
        self.ws_lock = threading.Lock()
        self.online = False
        self.stop_event = threading.Event()
        self.generation = 0
        self.events = queue.Queue()
        self.incoming = {}
        self.devices = []
        self.qr_image = None
        self.qr_expiry = 0
        self.started_worker = None
        self.free_relay = None
        self.free_token = 0
        self.pairing_pending = False
        self.transfer_items = {}
        self.file_send_lock = threading.Lock()
        self.failed_transfers = set()
        self.last_clipboard = None
        self.clipboard_was_ready = False
        self.public_url = ''

        self.root = Tk()
        self.root.title("AUREO LINK · 裝置傳輸工作台")
        self.root.configure(bg=BG)
        self.root.geometry("1120x800")
        self.root.minsize(1000, 800)
        resource_root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        icon = resource_root / "pwa" / "icons" / "aureo-link.ico"
        if icon.is_file():
            self.root.iconbitmap(str(icon))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.server_var = StringVar(value=self.config["server_url"])
        self.enroll_var = StringVar()
        self.folder_var = StringVar(value=self.config.get("save_folder", ""))
        self.message_var = StringVar()
        self.status_var = StringVar(value="● 尚未連線")
        self.countdown_var = StringVar(value="電腦上線後產生一次性 QR Code")
        self.public_url_var = StringVar(value='連線後顯示手機 PWA 網址')
        self.transfer_var = StringVar(value='沒有正在傳輸的檔案')
        self.transfer_percent = DoubleVar(value=0)
        self.clipboard_enabled = BooleanVar(value=self.config.get('clipboard_sync', True))
        self.clipboard_var = StringVar(value='文字剪貼簿：配對後啟用，支援文字與網址')
        self.build_ui()
        for item in self.history[-100:]:
            if isinstance(item, dict):
                self.show_chat(item.get("who", ""), item.get("text", ""), save=False)
        self.root.after(100, self.poll)
        self.root.after(1000, self.countdown)
        self.root.after(650, self.poll_clipboard)
        self.root.after(750, self.start_free_mode if self.config.get('mode') == 'free'
                        else self.connection_dialog if first_run else self.connect)

    def pill(self, parent, text, action, *, golden=False, padx=14, pady=9):
        return Button(parent, text=text, command=action, bg=GOLD if golden else CARD,
                      fg=BG if golden else TEXT, activebackground=GOLD_HI if golden else BORDER,
                      activeforeground=BG if golden else TEXT, relief="flat", bd=0,
                      font=("Microsoft JhengHei UI", 10, "bold"), padx=padx, pady=pady,
                      cursor="hand2", highlightthickness=0)

    def subtitle(self, parent, title, sub=""):
        Label(parent, text=title, bg=parent.cget("bg"), fg=TEXT,
              font=("Microsoft JhengHei UI", 11, "bold"), anchor="w").pack(fill="x")
        if sub:
            Label(parent, text=sub, bg=parent.cget("bg"), fg=MUTED,
                  font=("Microsoft JhengHei UI", 9), anchor="w").pack(fill="x", pady=(2, 8))

    def build_ui(self):
        top = Frame(self.root, bg=BG, height=74)
        top.pack(side="top", fill="x", padx=24, pady=(16, 5))
        Label(top, text="◈  AUREO", bg=BG, fg=GOLD,
              font=("Segoe UI", 21, "bold")).pack(side="left")
        Label(top, text="/ LINK", bg=BG, fg=TEXT,
              font=("Segoe UI", 21, "bold")).pack(side="left")
        Label(top, text="PRIVATE DEVICE WORKSPACE", bg=BG, fg=MUTED,
              font=("Consolas", 9)).pack(side="left", padx=(19, 0), pady=(9, 0))
        self.status = Label(top, textvariable=self.status_var, bg=BG, fg=MUTED,
                            font=("Microsoft JhengHei UI", 11, "bold"))
        self.status.pack(side="right", pady=11)

        main = Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        left = Frame(main, bg=PANEL, width=348, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        right = Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="left", fill="both", expand=True)

        title_row = Frame(left, bg=PANEL)
        title_row.pack(fill="x", padx=20, pady=(14, 4))
        Label(title_row, text="01 / 裝置配對", bg=PANEL, fg=GOLD,
              font=("Microsoft JhengHei UI", 12, "bold")).pack(side="left")
        self.pill(title_row, "⚙ 設定", self.connection_dialog, padx=8, pady=4).pack(side="right")
        Label(left, text="掃描下方 QR Code，建立私密傳送空間", bg=PANEL, fg=MUTED,
              font=("Microsoft JhengHei UI", 9)).pack(anchor="w", padx=20)
        qrframe = Frame(left, bg="#F9F7F2", width=208, height=208)
        qrframe.pack(pady=(10, 6))
        qrframe.pack_propagate(False)
        self.qr_label = Label(qrframe, text="QR CODE\n\nWAITING", bg="#F9F7F2", fg="#8C785C",
                              font=("Consolas", 14, "bold"), justify="center")
        self.qr_label.pack(fill="both", expand=True, padx=10, pady=10)
        self.pin_var = StringVar(value="手動配對碼：—")
        Label(left, textvariable=self.pin_var, bg=PANEL, fg=GOLD_HI,
              font=("Consolas", 14, "bold")).pack(pady=(1, 4))
        Label(left, textvariable=self.countdown_var, bg=PANEL, fg=GOLD,
              font=("Microsoft JhengHei UI", 9)).pack(pady=(0, 6))
        mobile_row = Frame(left, bg=PANEL)
        mobile_row.pack(fill='x', padx=20, pady=(0, 10))
        Label(mobile_row, text='手機 PWA 網址', bg=PANEL, fg=MUTED,
              font=('Microsoft JhengHei UI', 9)).pack(anchor='w')
        link_row = Frame(mobile_row, bg=PANEL)
        link_row.pack(fill='x', pady=(4, 0))
        Entry(link_row, textvariable=self.public_url_var, state='readonly', readonlybackground=CARD,
              fg=TEXT, relief='flat', font=('Consolas', 9), width=15).pack(side='left', fill='x', expand=True, ipady=7)
        self.pill(link_row, '開啟', self.open_mobile, padx=6, pady=5).pack(side='left', padx=(4, 0))
        self.pill(link_row, '複製', self.copy_mobile, padx=6, pady=5).pack(side='left', padx=(4, 0))
        section = Frame(left, bg=PANEL)
        section.pack(fill="x", padx=20)
        self.subtitle(section, "已配對裝置（限一台）", "移除目前裝置後，才能重新配對其他手機")
        self.device_list = Listbox(section, height=2, selectbackground="#5D4A31", selectforeground=TEXT,
                                   bg=CARD, fg=TEXT, highlightthickness=0, bd=0,
                                   font=("Microsoft JhengHei UI", 10), activestyle="none")
        self.device_list.pack(fill="x", pady=(0, 7))
        self.pill(section, "移除選取裝置", self.revoke, padx=8, pady=5).pack(anchor="e")

        footer = Frame(left, bg=PANEL)
        footer.pack(side="bottom", fill="x", padx=20, pady=17)
        self.subtitle(footer, "接收資料夾")
        folder_row = Frame(footer, bg=PANEL)
        folder_row.pack(fill="x", pady=(6, 7))
        Label(folder_row, textvariable=self.folder_var, bg=CARD, fg=MUTED, anchor="w",
              font=("Microsoft JhengHei UI", 9), padx=8, pady=10, width=22).pack(side="left", fill="x", expand=True)
        self.pill(folder_row, "選擇", self.choose_folder, padx=10, pady=8).pack(side="right", padx=(5, 0))


        chat_head = Frame(right, bg=PANEL)
        chat_head.pack(fill="x", padx=23, pady=(20, 10))
        Label(chat_head, text="02 / 即時共享空間", bg=PANEL, fg=GOLD,
              font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        Label(chat_head, text="訊息、連結、圖片及檔案  ·  20 MB 以內  ·  在線即時中繼",
              bg=PANEL, fg=MUTED, font=("Microsoft JhengHei UI", 9)).pack(anchor="w", pady=(5, 0))
        self.chat = Text(right, bg=PANEL, fg=TEXT, insertbackground=GOLD, state="disabled",
                         highlightthickness=0, bd=0, wrap="word", spacing1=8, spacing3=8,
                         font=("Microsoft JhengHei UI", 11), padx=22, pady=8)
        self.chat.tag_configure("me", foreground=GOLD)
        self.chat.tag_configure("other", foreground=GREEN)
        self.chat.tag_configure("system", foreground=MUTED)
        bar = Frame(right, bg=PANEL)
        bar.pack(side="bottom", fill="x", padx=21, pady=(10, 18))
        entry = Entry(bar, textvariable=self.message_var, bg=CARD, fg=TEXT, insertbackground=GOLD,
                      relief="flat", bd=0, font=("Microsoft JhengHei UI", 11))
        entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 8))
        entry.bind("<Return>", lambda _e: self.send_text())
        self.pill(bar, "傳檔案", self.select_file).pack(side="left", padx=(0, 6))
        self.pill(bar, "貼上傳送", self.send_clipboard).pack(side="left", padx=(0, 6))
        self.pill(bar, "傳送 →", self.send_text, golden=True).pack(side="left")
        clipboard = Frame(right, bg=CARD)
        clipboard.pack(side='bottom', fill='x', padx=21, pady=(4, 0))
        clip_row = Frame(clipboard, bg=CARD)
        clip_row.pack(fill='x', padx=8, pady=(5, 0))
        Checkbutton(clip_row, text='啟用雙向文字剪貼簿同步', variable=self.clipboard_enabled,
                    command=self.toggle_clipboard, bg=CARD, fg=TEXT, selectcolor=PANEL,
                    activebackground=CARD, activeforeground=TEXT,
                    font=('Microsoft JhengHei UI', 9)).pack(side='left')
        self.pill(clip_row, '同步目前剪貼簿', self.push_clipboard, padx=7, pady=4).pack(side='right')
        Label(clipboard, textvariable=self.clipboard_var, bg=CARD, fg=MUTED, anchor='w',
              wraplength=460, justify='left', font=('Microsoft JhengHei UI', 9)).pack(fill='x', padx=10, pady=(2, 7))
        progress = Frame(right, bg=PANEL)
        progress.pack(side='bottom', fill='x', padx=22, pady=(4, 2))
        Label(progress, textvariable=self.transfer_var, bg=PANEL, fg=GOLD, anchor='w',
              wraplength=460, justify='left', font=('Microsoft JhengHei UI', 9)).pack(fill='x')
        ttk.Style(self.root).configure('Aureo.Horizontal.TProgressbar', background=GOLD, troughcolor=CARD)
        ttk.Progressbar(progress, variable=self.transfer_percent, maximum=100,
                        style='Aureo.Horizontal.TProgressbar').pack(fill='x', pady=(4, 0))
        self.chat.pack(fill="both", expand=True)

    def update_transfer(self, tid, name, done, total, direction, *, state='active'):
        self.transfer_items[tid] = dict(name=name, done=done, total=total, direction=direction, state=state)
        active = list(self.transfer_items.values())
        item = self.transfer_items[tid]
        percent = min(100, int(done * 100 / total)) if total else (100 if state == 'waiting' else 0)
        self.transfer_var.set(f"{'正在傳送' if direction == 'send' else '正在接收'}：{name} · {percent}%"
                              + (' · 等待中繼確認' if state == 'waiting' else '')
                              + (f'（共 {len(active)} 個傳輸）' if len(active) > 1 else ''))
        total_bytes = sum(p['total'] for p in active)
        self.transfer_percent.set(sum(p['done'] for p in active) * 100 / total_bytes if total_bytes else 0)

    def finish_transfer(self, tid, message, *, success=True):
        self.transfer_items.pop(tid, None)
        if self.transfer_items:
            next_id, p = next(iter(self.transfer_items.items()))
            self.update_transfer(next_id, p['name'], p['done'], p['total'], p['direction'], state=p['state'])
        else:
            self.transfer_var.set(message)
            self.transfer_percent.set(100 if success else 0)

    def lock_pairing(self):
        self.qr_expiry = 0
        self.qr_image = None
        self.qr_label.configure(image='', text='已配對\n\nQR CODE 已停止')
        self.pin_var.set('配對碼  已停用')
        self.countdown_var.set('移除目前裝置後，可重新配對')

    def toggle_clipboard(self):
        self.config['clipboard_sync'] = self.clipboard_enabled.get()
        save_json(CONFIG_FILE, self.config)
        self.clipboard_was_ready = False
        self.clipboard_var.set('文字剪貼簿同步已啟用' if self.clipboard_enabled.get() else '文字剪貼簿同步已暫停')

    def push_clipboard(self):
        if not self.clipboard_enabled.get():
            self.clipboard_var.set('請先勾選文字剪貼簿同步')
            return
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ''
        if not text or len(text) > 12000:
            self.clipboard_var.set('請先複製 12,000 字以內的文字或網址')
            return
        if self.online and any(d.get('online') for d in self.devices) and self.send(
                {'type': 'clipboard', 'text': text, 'client_id': secrets.token_hex(8)}):
            self.last_clipboard = text
            self.clipboard_var.set('已同步到手機，點手機的「複製電腦內容」後即可貼上')
        else:
            self.clipboard_var.set('手機尚未連線，剪貼簿沒有送出')

    def poll_clipboard(self):
        ready = self.online and self.clipboard_enabled.get() and any(d.get('online') for d in self.devices)
        if ready:
            try:
                text = self.root.clipboard_get()
            except Exception:
                text = None
            if not self.clipboard_was_ready:
                self.last_clipboard = text
            elif text and text != self.last_clipboard and len(text) <= 12000:
                self.push_clipboard()
        self.clipboard_was_ready = bool(ready)
        if not self.stop_event.is_set():
            self.root.after(650, self.poll_clipboard)

    def connection_dialog(self):
        window = Toplevel(self.root)
        window.title("AUREO LINK / 伺服器設定")
        window.configure(bg=PANEL)
        window.geometry("560x465")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        body = Frame(window, bg=PANEL)
        body.pack(fill="both", expand=True, padx=26, pady=23)
        Label(body, text="伺服器連線設定", bg=PANEL, fg=GOLD,
              font=("Microsoft JhengHei UI", 16, "bold")).pack(anchor="w")
        Label(body, text="免費模式：電腦保持開啟，手機掃碼即可連線",
              bg=PANEL, fg=MUTED, font=("Microsoft JhengHei UI", 10)).pack(anchor="w", pady=(4, 17))
        def free_connect():
            window.grab_release()
            window.destroy()
            self.start_free_mode()
        self.pill(body, "啟動免費連線（不需伺服器）", free_connect, golden=True).pack(fill='x', pady=(0, 15))
        Label(body, text="桌面連線網址", bg=PANEL, fg=TEXT,
              font=("Microsoft JhengHei UI", 10)).pack(anchor="w")
        Entry(body, textvariable=self.server_var, bg=CARD, fg=TEXT, insertbackground=GOLD,
              relief="flat", font=("Consolas", 10)).pack(fill="x", ipady=8, pady=(5, 15))
        Label(body, text="首次註冊密碼（以後不需要，程式不會儲存）", bg=PANEL, fg=TEXT,
              font=("Microsoft JhengHei UI", 10)).pack(anchor="w")
        Entry(body, textvariable=self.enroll_var, bg=CARD, fg=TEXT,
              insertbackground=GOLD, show="●", relief="flat",
              font=("Consolas", 10)).pack(fill="x", ipady=8, pady=(5, 15))
        def confirm():
            window.grab_release()
            window.destroy()
            self.config['mode'] = 'custom'
            if self.free_relay:
                self.free_relay.stop()
                self.free_relay = None
            self.free_token += 1
            self.connect()
        self.pill(body, "儲存設定並連線 →", confirm, golden=True).pack(fill="x")

    def show_chat(self, who, text, *, save=True, kind="normal"):
        self.chat.configure(state="normal")
        tag = "me" if who == "我" else "system" if who == "系統" else "other"
        stamp = datetime.now().strftime("%H:%M")
        self.chat.insert(END, f"{who}  ·  {stamp}\n", tag)
        self.chat.insert(END, f"{text}\n\n")
        self.chat.see(END)
        self.chat.configure(state="disabled")
        if save:
            self.history.append({"who": who, "text": text})
            self.history = self.history[-160:]
            save_json(HISTORY_FILE, self.history)

    def send(self, packet):
        with self.ws_lock:
            ws = self.ws
            if not ws or not self.online or not ws.sock or not ws.sock.connected:
                return False
            try:
                ws.send(json.dumps(packet, ensure_ascii=False))
                return True
            except Exception:
                return False

    def start_free_mode(self):
        if self.free_relay:
            self.free_relay.stop()
        self.free_token += 1
        self.config['mode'] = 'free'
        save_json(CONFIG_FILE, self.config)
        self.generation += 1
        self.online = False
        for tid in list(self.incoming):
            self.drop_incoming(tid)
        with self.ws_lock:
            previous, self.ws = self.ws, None
        if previous:
            previous.close()
        self.qr_expiry = 0
        self.qr_label.configure(image='', text='CONNECTING')
        self.pin_var.set('配對碼  —')
        self.status_var.set('● 正在啟動免費連線…')
        self.status.configure(fg=GOLD)
        self.free_relay = FreeRelay(CONFIG_HOME, self.events, self.free_token)
        self.free_relay.start()

    def connect(self):
        url = self.server_var.get().strip()
        if not url.startswith(("ws://", "wss://")) or "/ws/desktop" not in url:
            messagebox.showerror(APP, "請填入 ws://.../ws/desktop 或 wss://.../ws/desktop")
            return
        self.config["server_url"] = url
        save_json(CONFIG_FILE, self.config)
        self.generation += 1
        version = self.generation
        self.online = False
        for tid in list(self.incoming):
            self.drop_incoming(tid)
        with self.ws_lock:
            previous = self.ws
            self.ws = None
        if previous:
            previous.close()
        self.status_var.set("● 連線中...")
        self.status.configure(fg=GOLD)
        enroll = self.enroll_var.get()
        self.started_worker = threading.Thread(target=self.network_worker,
                         args=(url, enroll, version), daemon=True)
        self.started_worker.start()

    def network_worker(self, url, enroll, version):
        while not self.stop_event.is_set() and version == self.generation:
            def on_open(sock):
                packet = {"type": "desktop_hello", "desktop_id": self.config["desktop_id"],
                          "secret": self.config["secret"], "name": self.config["name"],
                          "enroll_key": enroll}
                sock.send(json.dumps(packet, ensure_ascii=False))
            def on_message(_ws, data):
                try:
                    value = json.loads(data)
                    self.events.put((version, value))
                except (TypeError, ValueError):
                    pass
            def on_error(_ws, error):
                self.events.put((version, {"type": "status", "message": str(error)[:120]}))
            def on_close(_ws, code, reason):
                self.events.put((version, {"type": "disconnected"}))
            sock = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                        on_error=on_error, on_close=on_close)
            with self.ws_lock:
                if version != self.generation or self.stop_event.is_set():
                    return
                self.ws = sock
            try:
                sock.run_forever(ping_interval=30, ping_timeout=12)
            except Exception as e:
                self.events.put((version, {"type": "status", "message": str(e)[:120]}))
            if self.stop_event.wait(4):
                break

    def poll(self):
        try:
            for _ in range(50):
                version, event = self.events.get_nowait()
                if str(event.get('type', '')).startswith('free_'):
                    if version != self.free_token:
                        continue
                    if event['type'] == 'free_ready':
                        self.public_url = event['public_url']
                        self.public_url_var.set(self.public_url)
                        self.server_var.set(event['server_url'])
                        self.enroll_var.set(event['enroll_key'])
                        self.connect()
                        self.show_chat('系統', '免費連線已就緒。請用 iPhone 掃描 QR Code。\n關閉程式後通道會停止，下次啟動請重新掃碼。', save=False)
                    elif event['type'] == 'free_error':
                        self.online = False
                        self.qr_expiry = 0
                        self.qr_label.configure(image='', text='OFFLINE')
                        self.pin_var.set('配對碼  —')
                        self.status_var.set('● 免費連線失敗，請到設定重試')
                        self.status.configure(fg=MUTED)
                        self.show_chat('系統', event['message'], save=False)
                    else:
                        self.status_var.set('● ' + event['message'])
                elif version == self.generation:
                    self.handle(event)
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.root.after(80, self.poll)

    def handle(self, event):
        typ = event.get("type")
        if typ == "desktop_welcome":
            if self.config.get('mode') != 'free':
                self.public_url = self.server_var.get().replace('wss://', 'https://', 1).replace('ws://', 'http://', 1).split('/ws/desktop')[0]
                self.public_url_var.set(self.public_url)
            self.online = True
            self.status_var.set("● 已連線 / 可傳輸")
            self.status.configure(fg=GREEN)
            self.enroll_var.set("")
            self.devices = event.get("devices", [])
            self.fill_devices()
            if self.devices:
                self.lock_pairing()
            else:
                self.send({"type": "new_qr"})
            self.show_chat("系統", "伺服器連線成功，已準備接受配對。", save=False)
        elif typ == "qr":
            if self.devices or self.pairing_pending:
                return
            url = event.get("url", "")
            if not url.startswith(("https://", "http://")):
                return
            self.public_url = url.split('/?pair=')[0].rstrip('/')
            self.public_url_var.set(self.public_url)
            img = qrcode.make(url).convert("RGB").resize((188, 188), Image.Resampling.NEAREST)
            self.qr_image = ImageTk.PhotoImage(img)
            self.qr_label.configure(image=self.qr_image, text="")
            self.qr_expiry = time.monotonic() + int(event.get("ttl", 90))
            self.pin_var.set("配對碼  " + str(event.get("code", "—")))
        elif typ == "pair_request":
            self.pairing_pending = True
            self.qr_expiry = 0
            self.qr_label.configure(image='', text='等待配對確認')
            name = event.get("name", "行動裝置")
            approved = messagebox.askyesno("裝置配對確認", f"允許「{name}」連結這台電腦？\n\n只批准你認識的裝置。")
            self.send({"type": "pair_decision", "request_id": event.get("request_id"),
                       "approve": approved})
            self.pairing_pending = False
            if not approved:
                self.send({"type": "new_qr"})
            if approved:
                self.show_chat("系統", f"已批准 {name} 的配對要求。")
        elif typ in ("devices", "pair_locked"):
            had_devices = bool(self.devices)
            self.devices = event.get("devices", [])
            self.fill_devices()
            if self.devices:
                self.lock_pairing()
            elif had_devices:
                self.clipboard_was_ready = False
                self.send({'type': 'new_qr'})
        elif typ == 'pair_waiting':
            self.countdown_var.set('正在等待目前的配對要求完成')
        elif typ == "disconnected":
            self.online = False
            self.status_var.set("● 已離線 / 自動重連中")
            self.status.configure(fg=MUTED)
            self.qr_expiry = 0
            self.pin_var.set("配對碼  —")
            self.qr_label.configure(image="", text="OFFLINE")
            self.countdown_var.set("正在重新建立連線")
            for tid in list(self.incoming):
                self.drop_incoming(tid)
            self.transfer_items.clear()
            self.transfer_var.set('連線中斷，進行中的傳輸已停止')
            self.transfer_percent.set(0)
        elif typ == "status":
            self.status_var.set("● " + event.get("message", "連線異常")[:58])
            self.status.configure(fg=MUTED)
        elif typ == "chat":
            self.show_chat(event.get("from", "手機"), event.get("text", ""))
        elif typ == 'clipboard':
            text = event.get('text', '')
            if self.clipboard_enabled.get() and isinstance(text, str) and 0 < len(text) <= 12000:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(text)
                    self.last_clipboard = text
                    self.clipboard_var.set('手機文字已放入電腦剪貼簿，可直接 Ctrl+V 貼上')
                except Exception:
                    self.clipboard_var.set('無法更新電腦剪貼簿，請再同步一次')
        elif typ == 'transfer_progress':
            if event['id'] in self.failed_transfers:
                return
            self.update_transfer(event['id'], event['name'], event['done'], event['total'], 'send',
                                 state=event.get('state', 'active'))
        elif typ == 'transfer_failed':
            self.finish_transfer(event['id'], event['message'], success=False)
            self.show_chat('系統', event['message'], save=False)
        elif typ == 'sent':
            tid = event.get('id')
            item = self.transfer_items.get(tid)
            if item and item['direction'] == 'send':
                self.finish_transfer(tid, f"已送出：{item['name']}")
                self.show_chat('我', f"✓ 檔案已送出：{item['name']}")
        elif typ == "file_start":
            tid = event.get("id")
            size = event.get("size", -1)
            if not isinstance(size, int) or size < 0 or size > MAX_FILE:
                return
            folder = Path(self.folder_var.get()).expanduser()
            name = safe_filename(event.get("name", "file"))
            # Temporary file is never executable automatically. Final path is
            # guaranteed unique; existing user files are never overwritten.
            try:
                folder.mkdir(parents=True, exist_ok=True)
                import uuid
                temp = folder / (".aureo-" + uuid.uuid4().hex + ".part")
                f = temp.open("xb")
                self.incoming[tid] = {"file": f, "temp": temp, "folder": folder,
                                      "name": name, "expected": size, "bytes": 0, "seq": 0}
                self.update_transfer(tid, name, 0, size, 'receive')
            except OSError as e:
                self.show_chat("系統", f"無法準備儲存檔案：{e}")
                self.finish_transfer(tid, '無法儲存收到的檔案', success=False)
        elif typ == "file_chunk":
            tid = event.get("id")
            state = self.incoming.get(tid)
            if not state or state["seq"] != event.get("seq"):
                self.drop_incoming(tid)
                return
            try:
                raw = base64.b64decode(event["data"], validate=True)
                if state["bytes"] + len(raw) > state["expected"]:
                    raise ValueError("file length overflow")
                state["file"].write(raw)
                state["bytes"] += len(raw)
                state["seq"] += 1
                self.update_transfer(tid, state['name'], state['bytes'], state['expected'], 'receive')
            except (OSError, ValueError, KeyError):
                self.drop_incoming(tid)
        elif typ == "file_end":
            tid = event.get("id")
            state = self.incoming.pop(tid, None)
            if not state:
                return
            state["file"].close()
            if state["bytes"] != state["expected"]:
                state["temp"].unlink(missing_ok=True)
                self.show_chat("系統", "收到不完整的檔案，已丟棄。")
                self.finish_transfer(tid, '檔案接收不完整', success=False)
                return
            stem = Path(state["name"]).stem
            suffix = Path(state["name"]).suffix
            for n in range(10000):
                filename = state["name"] if n == 0 else f"{stem} ({n}){suffix}"
                target = state["folder"] / filename
                try:
                    # Avoid overwriting existing files, including on Windows.
                    with target.open("xb") as out, state["temp"].open("rb") as source:
                        while True:
                            chunk = source.read(1024 * 256)
                            if not chunk:
                                break
                            out.write(chunk)
                    state["temp"].unlink(missing_ok=True)
                    self.show_chat("手機檔案", f"✓ {filename}\n已儲存到：{target}")
                    self.finish_transfer(tid, f'接收完成：{filename}')
                    break
                except FileExistsError:
                    continue
                except OSError as e:
                    target.unlink(missing_ok=True)
                    state["temp"].unlink(missing_ok=True)
                    self.show_chat("系統", f"檔案儲存失敗：{e}")
                    self.finish_transfer(tid, '檔案儲存失敗', success=False)
                    break
        elif typ == "file_cancel":
            self.drop_incoming(event.get("id"))
        elif typ == "error":
            if event.get('id') in self.transfer_items:
                self.failed_transfers.add(event['id'])
                self.finish_transfer(event['id'], event.get('message', '傳輸失敗'), success=False)
            self.show_chat("系統", "⚠ " + event.get("message", "伺服器錯誤"), save=False)

    def drop_incoming(self, tid):
        state = self.incoming.pop(tid, None)
        if state:
            state["file"].close()
            state["temp"].unlink(missing_ok=True)
            self.finish_transfer(tid, '檔案傳輸已中斷', success=False)

    def fill_devices(self):
        self.device_list.delete(0, END)
        if not self.devices:
            self.device_list.insert(END, "尚無已配對的行動裝置")
            return
        for device in self.devices:
            mark = "●" if device.get("online") else "○"
            self.device_list.insert(END, f"{mark}  {device.get('name', '手機')}")

    def revoke(self):
        selected = self.device_list.curselection()
        if not selected or not self.devices:
            return
        device = self.devices[selected[0]]
        if messagebox.askyesno("移除裝置", f"確定取消 {device['name']} 的永久配對？"):
            self.send({"type": "device_revoke", "mobile_id": device["id"]})

    def open_mobile(self):
        if self.public_url.startswith(('https://', 'http://')):
            webbrowser.open(self.public_url)

    def copy_mobile(self):
        if self.public_url:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.public_url)
            self.last_clipboard = self.public_url
            self.show_chat('系統', '已複製目前手機 PWA 網址。', save=False)

    def choose_folder(self):
        location = filedialog.askdirectory(title="選擇收到檔案的存放資料夾",
                                           initialdir=self.folder_var.get())
        if location:
            self.folder_var.set(location)
            self.config["save_folder"] = location
            save_json(CONFIG_FILE, self.config)

    def send_text(self):
        text = self.message_var.get().strip()
        if not text:
            return
        if len(text) > 12000:
            self.show_chat("系統", "文字不可超過 12,000 字。", save=False)
            return
        if self.send({"type": "chat", "text": text, "client_id": secrets.token_hex(8)}):
            self.show_chat("我", text)
            self.message_var.set("")
        else:
            self.show_chat("系統", "電腦尚未連線，訊息沒有送出。", save=False)

    def select_file(self):
        filepaths = filedialog.askopenfilenames(title="選擇要傳送的檔案")
        for path in filepaths:
            self.send_file(Path(path))

    def send_clipboard(self):
        # Windows CF_HDROP (Explorer copied files) and clipboard screenshots.
        try:
            content = ImageGrab.grabclipboard()
        except (OSError, RuntimeError):
            content = None
        if isinstance(content, list) and content:
            for path in content:
                if Path(path).is_file():
                    self.send_file(Path(path))
            return
        if isinstance(content, Image.Image):
            fd, pathname = tempfile.mkstemp(prefix="Aureo-Screenshot-", suffix=".png")
            os.close(fd)
            content.save(pathname, format="PNG")
            self.send_file(Path(pathname), temporary=True)
            return
        try:
            text = self.root.clipboard_get()
        except Exception:
            text = ""
        if text:
            self.message_var.set(text[:12000])
            self.send_text()
        else:
            self.show_chat("系統", "剪貼簿目前沒有可支援的文字、圖片或檔案。", save=False)

    def send_file(self, path: Path, temporary=False):
        try:
            size = path.stat().st_size
        except OSError:
            self.show_chat("系統", f"無法讀取：{path}", save=False)
            return
        if size > MAX_FILE:
            self.show_chat("系統", f"檔案超過 20 MB：{path.name}", save=False)
            return
        if not self.online:
            self.show_chat("系統", "尚未連上伺服器，無法傳送檔案。", save=False)
            return
        self.show_chat("我", f"↑ 傳送檔案：{path.name}（{size / 1024 / 1024:.1f} MB）")
        threading.Thread(target=self.file_worker, args=(path, size, temporary), daemon=True).start()

    def file_worker(self, path: Path, size: int, temporary: bool):
        version = self.generation
        with self.file_send_lock:
            self._file_worker(path, size, temporary, version)

    def _file_worker(self, path, size, temporary, version):
        tid = secrets.token_hex(12)
        def progress(done, state='active'):
            self.events.put((version, {'type': 'transfer_progress', 'id': tid, 'name': path.name,
                                       'done': done, 'total': size, 'state': state}))
        try:
            if version != self.generation:
                raise RuntimeError('連線已變更，請重新選擇檔案')
            progress(0)
            import mimetypes
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if not self.send({"type": "file_start", "id": tid, "name": path.name,
                              "size": size, "mime": mime}):
                raise RuntimeError("失去連線")
            with path.open("rb") as f:
                seq = 0
                done = 0
                last_update = 0
                while chunk := f.read(CHUNK):
                    if version != self.generation:
                        raise RuntimeError('連線已變更')
                    if tid in self.failed_transfers:
                        raise RuntimeError('對方未接受檔案，請重新傳送')
                    if not self.send({"type": "file_chunk", "id": tid, "seq": seq,
                                      "data": base64.b64encode(chunk).decode("ascii")}):
                        raise RuntimeError("傳輸中途斷線")
                    seq += 1
                    done += len(chunk)
                    if time.monotonic() - last_update >= 0.1 or done == size:
                        progress(done)
                        last_update = time.monotonic()
                    time.sleep(0.004)
            progress(size, 'waiting')
            if not self.send({"type": "file_end", "id": tid}):
                raise RuntimeError("無法完成傳輸")
        except (OSError, RuntimeError) as e:
            self.events.put((version, {"type": "transfer_failed", 'id': tid, "message": f"檔案傳輸失敗：{e}"}))
        finally:
            if temporary:
                path.unlink(missing_ok=True)

    def countdown(self):
        if self.online and not self.devices and not self.pairing_pending:
            seconds = max(0, int(self.qr_expiry - time.monotonic()))
            if seconds <= 20:
                # Server issues a new QR; no QR code is accepted after TTL.
                if seconds == 20 or seconds == 0:
                    self.send({"type": "new_qr"})
            self.countdown_var.set(f"一次性配對碼 · {seconds} 秒後更新")
        self.root.after(1000, self.countdown)

    def on_close(self):
        self.stop_event.set()
        if self.free_relay:
            self.free_relay.stop()
            if self.free_relay.thread:
                self.free_relay.thread.join(timeout=7)
        self.generation += 1
        with self.ws_lock:
            previous = self.ws
            self.ws = None
        if previous:
            previous.close()
        for tid in list(self.incoming):
            self.drop_incoming(tid)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Desktop().run()
