"""Local relay with a temporary, account-free Cloudflare HTTPS tunnel."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading

from aiohttp import web
from server.app import create_app
from server.directory_client import Publisher


class FreeRelay:
    def __init__(self, home: Path, events: queue.Queue, token: int, *, tunnel_path: Path | None = None):
        self.home = home
        self.events = events
        self.token = token
        self.stopping = threading.Event()
        self.thread = None
        self.tunnel_path = tunnel_path

    def emit(self, kind, **values):
        self.events.put((self.token, {"type": kind, **values}))

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()

    def run(self):
        try:
            asyncio.run(self.serve())
        except Exception as error:
            if not self.stopping.is_set():
                self.emit("free_error", message=f"免費連線啟動失敗：{error}")

    async def serve(self):
        root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
        tools = root / 'tools'
        executable = self.tunnel_path or tools / 'cloudflared.exe'
        if not executable.is_file():
            raise RuntimeError('找不到通道程式，請重新下載官方完整版本')
        self.home.mkdir(parents=True, exist_ok=True)
        enroll = secrets.token_urlsafe(48)
        app = create_app(db_path=self.home / 'free-relay.sqlite3',
                         public_url='http://localhost:8787', enroll_key=enroll)
        # Only migrate legacy tunnel-cookie devices. Fixed-PWA credentials and
        # their one-device slot survive process restarts and tunnel changes.
        app['hub'].db.execute('DELETE FROM mobiles WHERE portable=0')
        app['hub'].db.commit()
        runner = web.AppRunner(app, access_log=None)
        process = None
        log_task = None
        directory_task = None
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            local = f'http://127.0.0.1:{port}'
            self.emit('free_status', message='正在建立免費 HTTPS 連線，請稍候…')
            # Explicit config keeps existing user Cloudflare settings untouched.
            config = self.home / 'free-tunnel.yml'
            config.write_text('{}\n', encoding='utf-8')
            process = await asyncio.create_subprocess_exec(
                str(executable), 'tunnel', '--config', str(config), '--no-autoupdate',
                '--protocol', 'http2', '--url', local,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            ready = asyncio.Event()
            url = None

            async def read_logs():
                nonlocal url
                with (self.home / 'free-tunnel.log').open('w', encoding='utf-8') as log:
                    while line := await process.stdout.readline():
                        text = line.decode('utf-8', errors='replace')
                        log.write(text)
                        log.flush()
                        match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', text)
                        if match:
                            url = match.group()
                        if url and 'Registered tunnel connection' in text:
                            app['hub'].public_url = url
                            ready.set()

            log_task = asyncio.create_task(read_logs())
            for _ in range(180):
                if self.stopping.is_set():
                    return
                if process.returncode is not None:
                    raise RuntimeError('通道程式已結束，請查看 free-tunnel.log 或重新啟動')
                if ready.is_set():
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError('建立通道逾時，請確認網路連線後再試')
            app['hub'].publisher = Publisher(self.home, app['hub'])
            directory_task = asyncio.create_task(app['hub'].publisher.run())
            self.emit('free_ready', server_url=f'ws://127.0.0.1:{port}/ws/desktop',
                      enroll_key=enroll, public_url=url)
            while not self.stopping.is_set():
                if process.returncode is not None:
                    raise RuntimeError('免費通道已中斷，請到設定重新啟動免費模式')
                await asyncio.sleep(0.5)
        finally:
            if directory_task:
                directory_task.cancel()
                await asyncio.gather(directory_task, return_exceptions=True)
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if log_task:
                await asyncio.gather(log_task, return_exceptions=True)
            # Close live sockets before aiohttp cleanup to avoid a shutdown delay.
            for ws in list(app['hub'].desktops.values()):
                await ws.close()
            for sockets in list(app['hub'].mobile_sockets.values()):
                for ws in list(sockets):
                    await ws.close()
            await runner.cleanup()
