# AUREO LINK — Windows × iPhone PWA 即時共享工作台

> Windows 單檔工具與完整原始碼。延續 AUREATE 的霧黑、香檳金、繁體中文工具介面。
> Windows EXE + iOS 主畫面 PWA + HTTPS/WSS 中繼伺服器。**非端對端加密**，自架中繼伺服器可存取即時傳輸內容。

## 下載與開始使用

**[下載 Windows EXE](https://github.com/stu310101-arch/aureo-link/releases/latest/download/AureoLink.exe)** · **[手機入口](https://stu310101-arch.github.io/aureo-link/phone/)** · **[下載頁](https://stu310101-arch.github.io/aureo-link/)** · [完整 Release](https://github.com/stu310101-arch/aureo-link/releases/latest)

1. 下載並開啟 `AureoLink.exe`，等待免費 HTTPS 通道與 QR Code 出現。
2. 用 iPhone 相機掃碼，或從「手機入口」貼上電腦顯示的連線網址。
3. 在電腦確認配對，即可互傳。電腦左側也能開啟或複製目前手機 PWA 網址。

單獨下載 EXE 即可使用，無須另裝 Python 或附帶 tools 資料夾。免費模式由**每位使用者自己的電腦**提供服務；需保持該電腦開機、連網並開著程式。固定手機入口協助開啟使用者的連線，實際 PWA 在該電腦的臨時 HTTPS 網址運作。程式重啟後請重新掃碼。

## 具備功能

- **第二版更新**：一次只允許一個已配對手機，成功後停止核發與更新 QR/PIN，移除後才能再配對。既有多裝置資料會保留最近一台。
- 手機與桌面顯示傳送／接收百分比、等待中繼確認、送出、接收完成及中斷提示。
- 雙向**文字與網址剪貼簿**：Windows 配對在線時自動同步新複製的文字；手機送出的文字自動寫入 Windows 剪貼簿，可直接 Ctrl+V。iPhone 必須在頁面點「手機複製 → 電腦可貼上」（或長按專用欄位貼上）送出；收到電腦內容後點「複製電腦內容」。PWA 無法提供 iOS 原生背景 Universal Clipboard，也不會背景讀取其他 App 的剪貼簿。圖片與檔案仍使用傳檔功能。

- **免費模式（預設）**：Windows EXE 內建本機中繼與官方 cloudflared，建立免費 HTTPS 通道。無須自備伺服器、網域或帳號。啟動 `AureoLink.exe`，等待 QR Code 出現，再由 iPhone 掃碼並在電腦確認。
- 免費模式需電腦保持開機與連網，關閉程式即停止通道；每次啟動網址改變，手機需要重新掃碼。Cloudflare Quick Tunnel 為測試用途、無可用性保證，不等同固定網址的長期託管。手機加入主畫面後的網址也會隨通道過期。
- EXE 已內嵌 cloudflared，來自 Cloudflare 官方 GitHub release，建置時比對官方 SHA256。從原始碼執行時，`FETCH_TUNNEL.py` 會下載並驗證至 `tools/`。
- 原有自架伺服器模式保留，可在「設定」填入自訂 WSS 網址和註冊密碼。

- Windows 開啟桌面程式 → 伺服器核發每 **90 秒失效** 的動態 QR Code 和 **8 位數配對碼**。
- 手機掃碼或輸入配對碼 → 電腦視窗顯示授權詢問 → **只有電腦同意才建立信任裝置**。
- 伺服器 SQLite 保存配對狀態，手機保存 **HttpOnly / SameSite Cookie**；iOS 17.2+ 安裝 PWA 會複製 Safari 的 Cookie，幫助做到「掃一次、下次開啟直接連線」。
- 任一方在連線時傳送文字、網址、圖片或檔案；檔案使用 48 KiB WebSocket 分段，**單檔上限 20 MiB**。
- Windows 收到檔案時儲存在使用者指定資料夾，不會覆蓋同名檔案，禁止路徑穿越，也不會自動執行收到的檔案。
- Windows 支援檔案挑選、貼上剪貼簿文字、**Windows 檔案總管複製的檔案**、剪貼簿截圖（手動點「貼上傳送」）。
- iOS PWA 支援挑選圖片/檔案、輸入/貼上文字、圖片預覽、下載及呼叫分享表單保存到「檔案」；能顯示已連線 / 離線。
- 斷線自動重連、已信任裝置清單和撤銷配對。
- 手機本機保留最近 120 筆文字或檔案**名稱紀錄**；桌面本機保留最近 160 筆訊息。**檔案資料本身不跨重啟保存於網頁**。
- 中繼服務**不留存聊天訊息與檔案**，只在已驗證的線上連線間轉送；無離線代收。

## 架構

```
 ┌──────────────────────┐     WSS/TLS       ┌──────────────────────────┐
 │ Windows AureoLink.exe│ ◀───────────────▶ │ Caddy HTTPS + Python     │
 │ 桌面裝置永久憑證       │                    │ aiohttp + SQLite         │
 │ QR / 資料夾 / 文字聊天 │                    │ 僅中繼，不儲存訊息檔案    │
 └──────────────────────┘                    └──────────┬───────────────┘
                                                       │ HTTPS / WSS
                                            ┌──────────▼───────────────┐
                                            │ iPhone Safari / PWA       │
                                            │ iOS 主畫面 + cookie 配對   │
                                            │ 聊天 / 分享 / 檔案         │
                                            └──────────────────────────┘
```

## 1. 先在伺服器部署 PWA + 中繼服務（正式使用）

要跨 Wi-Fi / 行動網路傳輸，必須有可透過網路連接的伺服器與 **HTTPS 網域**。程式會自動把 HTTP 與 WebSocket 接到同一個網站網址。使用 Docker 和 Caddy 是最短的部署方式。

1. 準備有公網 IP 的 VPS 和一組網域，例如 `link.example.com`。網域 A/AAAA 記錄指向 VPS，開通對外 TCP **80/443**（和可選 UDP 443）。
2. 將本專案上傳 VPS；複製 `.env.example` 為 `.env`。
3. 修改 `.env` 的 `DOMAIN` 和 `AUREO_ENROLL_KEY`，後者需要足夠長且無法猜測；**不得提交 GitHub**。可用以下指令生成金鑰：

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. 執行：

   ```bash
   docker compose up -d --build
   ```

5. 在手機 Safari 開啟 `https://link.example.com`，應可看到黑金配對畫面。HTTPS 憑證由 Caddy 自動申請。記得備份 Docker 命名儲存卷中的 SQLite 檔案。

### 僅在同一台開發電腦上測試

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-server.txt
# PowerShell:
$env:AUREO_ENROLL_KEY="your-private-development-key"
$env:AUREO_PUBLIC_URL="http://localhost:8787"
python -m server.app
```

本機測試使用 `http://localhost:8787`，**只能在本機瀏覽器測試**。真實 iPhone 掃碼會把 `localhost` 指向手機自己；手機的 PWA、剪貼簿功能需要正式 **HTTPS** 服務。不要直接公開 HTTP 開發埠到網際網路。

## 2. Windows 桌面端

### 直接執行原始碼

- 安裝 Windows 10/11 x64 的 Python 3.12+。
- 雙擊 `RUN_DESKTOP.cmd`，或自行使用 `pip install -r requirements-desktop.txt` 後執行 `python desktop/app.py`。
- 在桌面 GUI 左上角點「⚙ 設定」，將「桌面連線網址」填入：`wss://link.example.com/ws/desktop`。
- 「首次註冊密碼」填入你在伺服器 `.env` 的 `AUREO_ENROLL_KEY`，按「重新連線」。**只有這台電腦首次註冊時需要填寫**，之後儲存的獨立裝置憑證會自動連線。
- 成功後左側顯示動態 QR 和 8 位數配對碼。挑選「接收資料夾」例如 `D:\AureoShare`。

### 建立 EXE

在 **Windows 電腦**上雙擊 `BUILD_WINDOWS.cmd`。它會安裝 PyInstaller 與相依套件並產生：

```
dist\AureoLink.exe
```

也可推送到 GitHub 後，在 Actions 手動執行 `Build Windows EXE` 並下載 `AureoLink-Windows-x64` artifact。建置前會先執行 Python 測試，通過後才產出 EXE。`BUILD_WINDOWS.cmd --no-pause` 可供自動化建置使用。首次啟動預設進入免費連線模式；單檔 EXE 已內含 Python、網頁、中繼服務與 cloudflared，使用者不需要另行安裝 Python。EXE 未加數位簽章。

## 3. iPhone 使用方式

1. 在電腦開啟 `AureoLink.exe`，確認顯示已連線與配對 QR。
2. 用 iPhone 相機掃 QR，開啟 Safari 網頁。
3. 在 Windows 桌面彈窗按「是」確認這支 iPhone。
4. Safari 網頁進入即時共享空間。在 Safari「分享 → 加入主畫面 → 開啟為 Web App／加入」，之後點主畫面上的 AUREO LINK 圖示即可重連。
5. 如果手機安裝後未保留 Safari 配對（例如較舊 iOS 或瀏覽資料被清除），**在已安裝的 PWA 內輸入電腦顯示的 8 位數配對碼**，桌面再次確認即可。

## 限制與安全注意

| 功能 / 環境 | MVP 狀態 | 說明 |
|---|---|---|
| Windows EXE | 可攜式單檔程式 | `BUILD_WINDOWS.cmd` / GitHub Actions；未提供簽章安裝器 |
| iOS 主畫面 PWA | 支援 | 使用者須手動從瀏覽器加入主畫面；網站不能強制安裝 |
| iPhone 自動監聽剪貼簿 | **不支援無提示常駐監聽** | 受 Safari 隱私及使用者手勢限制；請使用貼上、分享或手動選檔 |
| iPhone 自動指定檔案儲存路徑 | **不支援** | 由 iOS 檔案 / 分享介面決定；Windows EXE 可指定路徑 |
| iOS 背景接收 / 離線訊息 | **不支援** | PWA 背景執行會被暫停；雙方同時在線才能傳輸 |
| 已信任手機 | 限一台 | 配對後 QR/PIN 停止；移除後才能配對其他手機 |
| 檔案傳輸上限 | 20 MiB / 檔 | 本版用 WebSocket Base64 中繼，有額外傳輸流量 |
| 檔案斷點續傳 / 大檔傳輸 | 尚未實作 | 建議下一版加入 WebRTC + TURN 或串流上傳 |
| 雙方完整雲端訊息紀錄 | 尚未實作 | 各裝置儲存有限的本機文字紀錄，伺服器不留訊息 |
| 文字剪貼簿 | Windows 自動、iPhone 點擊操作 | 支援文字／網址；iPhone PWA 受使用者手勢與背景限制 |
| 端對端加密（E2EE） | **尚未實作** | HTTPS/WSS 僅加密傳輸路徑，伺服器中繼仍能存取內容 |

**正式公開前必做的強化**：定期備份 DB、將桌面私密金鑰改為 Windows DPAPI/Credential Manager 管理、完善傳輸確認/重試、防濫用限速/容量配額、安全監控、惡意檔案提醒、端對端加密及實機 iOS/Windows 相容性測試。請勿使用短弱的註冊密碼；如果洩露，立即變更註冊密碼。

## 驗證

```bash
pip install -r requirements-dev.txt
python -m pytest -q
node --check pwa/app.js
```

`tests/test_protocol.py` 包含配對核准、QR + PIN 單次有效、裝置憑證重連、文字雙向傳送、檔案分段、路徑清理、單檔大小限制、撤銷已信任裝置、Origin 阻擋。

## UI 預覽（非真實已配對裝置畫面）

- `preview-pairing-mobile.png`：iPhone 首頁與配對方式示意。
- `preview-chat-mobile.png`：iPhone 即時聊天視窗示意。
- `preview-chat-desktop-web.png`：網頁在寬螢幕時的版面示意。
- `preview-windows-ui.png`：Tkinter 桌面 EXE 畫面示意；**預覽 QR/PIN 不是真正可用的配對憑證**。

## 參考設計

- [AUREO / screen_recoder](https://github.com/stu310101-arch/screen_recoder) — 原生 Windows 工具流程
- [AUREATE](https://github.com/stu310101-arch/AUREATE) — 黑金、極簡、繁體中文工作台

MIT-style development sample; see `LICENSE.txt`. Production deployment and security review remain the deployer's responsibility.
