(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const MAX_FILE = 20 * 1024 * 1024;
  const CHUNK = 48 * 1024;
  const connection = window.AmosConnection;
  const launchLink = location.href;
  let pairBusy = false;
  let lookingUp = false;
  let restoring = false;
  let ws = null;
  let paired = false;
  let peerOnline = false;
  let desktopID = '';
  let retryTimer = null;
  let retryDelay = 1500;
  let transfers = new Map();
  const uploads = new Map();
  const progressRows = new Map();
  let sendingFiles = false;
  let remoteClipboard = '';
  let toastTimeout = 0;
  let currentPin = new URLSearchParams(location.search).get('pair') || '';
  let historyKey = '';
  let savingHistory = false;
  history.replaceState({}, '', location.pathname); // never keep one-time pairing token in address bar

  function toast(text) {
    const node = $('toast');
    node.textContent = text;
    node.classList.add('show');
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => node.classList.remove('show'), 3200);
  }
  function safeText(value) { return typeof value === 'string' ? value : ''; }
  function sizeLabel(size) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 ** 2).toFixed(1)} MB`;
  }
  function setStatus(label, connected = false) {
    $('connectionPill').innerHTML = '';
    const dot = document.createElement('span'); dot.className = 'signal';
    $('connectionPill').append(dot, document.createTextNode(` ${label}`));
    $('connectionPill').className = `pill ${connected ? 'online' : 'offline'}`;
    $('chatStatus').textContent = label;
    $('computerStatus').textContent = connected ? '可即時傳送' : '未連線，等待電腦上線';
    $('deviceDot').classList.toggle('online', connected);
    peerOnline = connected;
  }
  function showPair() {
    paired = false;
    $('pairView').hidden = false;
    $('roomView').hidden = true;
    $('pairWaiting').hidden = true;
    $('pairForm').hidden = false;
    setStatus('尚未配對');
    remoteClipboard = '';
    $('receiveClipboardBtn').disabled = true;
    $('clipboardStatus').textContent = '配對後可同步文字剪貼簿';
  }
  function showRoom(data) {
    paired = true;
    $('pairView').hidden = true;
    $('roomView').hidden = false;
    $('computerName').textContent = data.desktop_name || 'Windows 電腦';
    if (desktopID !== data.desktop_id) {
      desktopID = data.desktop_id;
      historyKey = 'aureo_history_' + desktopID;
      renderSavedMessages();
    }
  }
  function installGuide() {
    const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
    $('installNote').hidden = !isIOS || standalone || sessionStorage.getItem('hide_install') === 'yes';
  }
  async function getMe() { return connection.me(); }
  async function acceptLink(value) {
    if(lookingUp||pairBusy)return;
    lookingUp=true;
    $('scanBtn').disabled=true;
    try {
      const entry = await connection.useQr(value);
      if (ws) { const old=ws; ws=null; old.close(); }
      if (entry.resumed) { showRoom(entry.user); connect(); toast('已恢復原本配對'); }
      else if (entry.code) await claimPair(entry.code);
      else throw new Error('QR Code 沒有配對資料，請重新產生。');
    } catch (error) { $('pairError').textContent=error.message || '無法讀取配對 QR Code。'; }
    finally{lookingUp=false;$('scanBtn').disabled=false;}
  }
  async function loadApp() {
    if (restoring) return;
    restoring=true;
    installGuide();
    try {
      if (location.hash.includes('relay=') || new URL(launchLink).hash.includes('relay=')) {
        const incoming = window.__amosLaunchConsumed ? '' : launchLink;
        window.__amosLaunchConsumed=true;
        if (incoming) { await acceptLink(incoming); return; }
      }
      setStatus('正在恢復連線...');
      const me=await getMe();
      if (me?.paired) { showRoom(me); connect(); }
      else if (connection.saved && me === null) {
        showRoom({desktop_id:connection.saved.locator,desktop_name:'已記住的 Windows 電腦'});
        setStatus('電腦目前離線，配對已保留');
        scheduleReconnect();
      } else {
        if (me && !me.paired) connection.forget();
        showPair();
        if (currentPin && (/^[a-zA-Z0-9_\-]{48}$/.test(currentPin) || /^[0-9]{8}$/.test(currentPin))) {
          await claimPair(currentPin); currentPin='';
        }
      }
    } finally { restoring=false; }
  }
  async function claimPair(code) {
    if (pairBusy) return;
    pairBusy=true;
    $('pairError').textContent = '';
    $('pairWaiting').hidden = false;
    $('pairForm').hidden = true;
    $('pairWaitingTitle').textContent = '正在請求電腦批准...';
    const phoneName = /iPad/.test(navigator.userAgent) ? 'iPad' : /iPhone/.test(navigator.userAgent) ? 'iPhone' : '行動裝置';
    try {
      const res = await connection.request('/api/pair/claim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, name: phoneName }),
      });
      if (!res.ok) throw new Error(res.status === 410 ? '配對碼已過期，請使用電腦畫面上最新的 QR Code / 配對碼。' : res.status === 409 ? '這台電腦已有配對裝置或正在確認配對。請先在電腦移除原裝置。' : '配對失敗，請確認電腦在線上及配對碼正確。');
      const pair = await res.json();
      $('pairWaitingTitle').textContent = '等待電腦確認';
      for (let tries = 0; tries < 95; tries++) {
        await new Promise(resolve => setTimeout(resolve, 1800));
        const statusRes = await connection.request('/api/pair/status', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:pair.request_id,proof:pair.proof})});
        if (!statusRes.ok) throw new Error('配對要求已過期，請重新掃描 QR Code。');
        const result = await statusRes.json();
        if (result.status === 'denied') throw new Error('電腦已拒絕配對。');
        if (result.status === 'approved') {
          connection.approved(result);
          toast('配對成功，可以開始傳送');
          const me = await getMe();
          if (!me || !me.paired) throw new Error('無法讀取配對狀態，請重新開啟網頁。');
          showRoom(me);
          connect();
          return;
        }
      }
      throw new Error('電腦未確認，配對逾時。');
    } catch (err) {
      $('pairError').textContent = err.message || '無法建立連線。';
      $('pairWaiting').hidden = true;
      $('pairForm').hidden = false;
    } finally { pairBusy=false; }
  }
  function connect() {
    if (!paired || ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    clearTimeout(retryTimer);
    setStatus('正在連線...');
    try { ws = new WebSocket(connection.socketUrl()); } catch (_) { scheduleReconnect(); return; }
    const socket=ws;
    ws.onopen = () => { if(ws!==socket)return; connection.hello(socket); retryDelay = 1500; setStatus('已連到伺服器'); };
    ws.onmessage = async event => {
      if(ws!==socket)return;
      let p;
      try { p = JSON.parse(event.data); } catch (_) { return; }
      switch (p.type) {
        case 'welcome':
          setStatus(p.online ? '電腦已在線' : '電腦目前離線', !!p.online); break;
        case 'presence':
          setStatus(p.online ? '電腦已在線' : '電腦目前離線', !!p.online); break;
        case 'chat':
          addTextMessage(safeText(p.from) || '電腦', safeText(p.text), false); break;
        case 'clipboard':
          remoteClipboard = safeText(p.text);
          $('receiveClipboardBtn').disabled = !remoteClipboard;
          $('clipboardStatus').textContent = '電腦文字已同步，點「複製電腦內容」後就能在其他 App 貼上。';
          toast('收到電腦剪貼簿，點「複製電腦內容」即可貼上'); break;
        case 'file_start': beginFile(p); break;
        case 'file_chunk': appendChunk(p); break;
        case 'file_end': finishFile(p); break;
        case 'file_cancel':
          transfers.delete(p.id); finishProgress(p.id, '接收已中斷', false); toast('對方已取消檔案傳輸'); break;
        case 'error':
          if (uploads.has(p.id)) { uploads.get(p.id).failed = true; uploads.get(p.id).file = null; finishProgress(p.id, p.message || '傳送失敗', false); }
          toast(p.message || '傳送失敗'); break;
        case 'sent': {
          const item = uploads.get(p.id);
          if (item && !item.failed) {
            finishProgress(p.id, `已送出：${item.file.name}`);
            showFileMessage('我', item.file.name, item.file.size, true, item.file, item.mime);
            uploads.delete(p.id);
          }
          break;
        }
      }
    };
    ws.onclose = async event => {
      if(ws!==socket)return;
      ws = null;
      setStatus('連線中斷');
      transfers.clear();
      for (const [id, item] of uploads) { item.failed = true; finishProgress(id, '連線中斷，傳送未完成', false); }
      uploads.clear();
      for (const id of progressRows.keys()) finishProgress(id, '連線中斷，傳輸已停止', false);
      if (!paired) return;
      if (event.code === 4001) { setStatus('已在另一個視窗連線'); return; }
      if (event.code === 4003 || event.code === 1008) {
        const me = await getMe();
        if (me && !me.paired) { connection.forget(); showPair(); toast('電腦已取消這台手機的配對'); return; }
      }
      scheduleReconnect();
    };
    ws.onerror = () => { /* onclose handles reconnect */ };
  }
  function scheduleReconnect() {
    if (!paired) return;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(async () => {
      const me=await getMe();
      if (!paired) return;
      if (me && !me.paired) { connection.forget(); showPair(); return; }
      connect();
    }, retryDelay);
    retryDelay = Math.min(retryDelay * 1.6, 16000);
  }
  function canSend() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !peerOnline) {
      toast('電腦目前不在線上，請先開啟 Windows EXE');
      return false;
    }
    return true;
  }
  function sendClipboard(text) {
    if (!text || !text.trim() || !canSend()) return false;
    if (text.length > 12000) { toast('剪貼簿文字不可超過 12,000 字'); return false; }
    ws.send(JSON.stringify({type: 'clipboard', text, client_id: crypto.randomUUID().replaceAll('-', '')}));
    $('clipboardStatus').textContent = '已送到電腦；電腦啟用雙向文字剪貼簿同步時，可直接 Ctrl+V 貼上。';
    return true;
  }
  function updateProgress(id, name, done, total, direction, waiting = false) {
    let item = progressRows.get(id);
    if (!item) {
      const row = document.createElement('div'); row.className = 'transfer-row';
      const label = document.createElement('div');
      const bar = document.createElement('progress'); bar.max = total || 1;
      row.append(label, bar); $('transferList').appendChild(row);
      item = {row, label, bar}; progressRows.set(id, item);
    }
    clearTimeout(item.timer);
    if (item.finished) return;
    const percent = total ? Math.min(100, Math.floor(done / total * 100)) : (waiting ? 100 : 0);
    item.label.textContent = `${direction === 'send' ? '正在傳送' : '正在接收'}：${name} · ${percent}%${waiting ? ' · 等待中繼確認' : ''}`;
    item.bar.value = total ? done : (waiting ? 1 : 0);
  }
  function finishProgress(id, message, success = true) {
    const item = progressRows.get(id);
    if (!item || item.finished) return;
    item.finished = true;
    clearTimeout(item.timer);
    item.label.textContent = `${success ? '✓' : '⚠'} ${message}`;
    item.bar.value = success ? item.bar.max : 0;
    item.row.classList.toggle('transfer-error', !success);
    item.timer = setTimeout(() => { item.row.remove(); progressRows.delete(id); }, 6000);
  }
  function sendText() {
    const msg = $('messageInput').value.trim();
    if (!msg || !canSend()) return;
    if (msg.length > 12000) { toast('文字不可超過 12,000 字'); return; }
    ws.send(JSON.stringify({ type: 'chat', text: msg, client_id: crypto.randomUUID().replaceAll('-', '') }));
    addTextMessage('我', msg, true);
    $('messageInput').value = '';
    $('messageInput').style.height = '';
  }
  function clearWelcome() {
    const welcome = $('messages').querySelector('.welcome');
    if (welcome) welcome.remove();
  }
  function messageFrame(who, mine) {
    clearWelcome();
    const group = document.createElement('div');
    group.className = `bubble-group ${mine ? 'mine' : who === '系統' ? 'system' : 'theirs'}`;
    const byline = document.createElement('div');
    byline.className = 'byline';
    byline.textContent = `${who} · ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
    group.appendChild(byline);
    $('messages').appendChild(group);
    $('messages').scrollTop = $('messages').scrollHeight;
    return group;
  }
  function linkify(container, text) {
    const urlRE = /https?:\/\/[^\s<>"']+/gi;
    let last = 0;
    for (const match of text.matchAll(urlRE)) {
      container.appendChild(document.createTextNode(text.slice(last, match.index)));
      try {
        const url = new URL(match[0]);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('protocol');
        const a = document.createElement('a');
        a.href = url.href;
        a.target = '_blank';
        a.rel = 'noreferrer noopener';
        a.textContent = match[0];
        container.appendChild(a);
      } catch (_) { container.appendChild(document.createTextNode(match[0])); }
      last = match.index + match[0].length;
    }
    container.appendChild(document.createTextNode(text.slice(last)));
  }
  function addTextMessage(who, text, mine, remember = true) {
    const group = messageFrame(who, mine);
    const bubble = document.createElement('div'); bubble.className = 'bubble';
    linkify(bubble, text);
    group.appendChild(bubble);
    const actions = document.createElement('div'); actions.className = 'message-actions';
    const copy = document.createElement('button'); copy.textContent = '複製文字';
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(text); toast('已複製到剪貼簿'); }
      catch (_) { toast('無法複製，請長按訊息選取'); }
    };
    actions.appendChild(copy); group.appendChild(actions);
    $('messages').scrollTop = $('messages').scrollHeight;
    if (remember) keepHistory({ kind: 'text', who, text, mine });
  }
  function keepHistory(item) {
    if (!historyKey || savingHistory) return;
    try {
      const items = JSON.parse(localStorage.getItem(historyKey) || '[]');
      items.push(item);
      localStorage.setItem(historyKey, JSON.stringify(items.slice(-120)));
    } catch (_) { /* storage can be disabled by browser settings */ }
  }
  function renderSavedMessages() {
    $('messages').innerHTML = '<div class="welcome"><div class="welcome-mark">◈</div><h3>這裡是你的傳送空間</h3><p>將檔案、圖片、網址或文字放在這裡，另一端就會收到。</p></div>';
    savingHistory = true;
    try {
      const items = JSON.parse(localStorage.getItem(historyKey) || '[]');
      for (const item of items.slice(-120)) {
        if (item.kind === 'text') addTextMessage(item.who, item.text, !!item.mine, false);
        else if (item.kind === 'file') showFileMessage(item.who, item.name, item.size, item.mine, null, null, false);
      }
    } catch (_) { /* history is optional */ }
    savingHistory = false;
  }
  function showFileMessage(who, name, size, mine, blob, mime, remember = true) {
    const group = messageFrame(who, mine);
    const node = document.createElement('div'); node.className = 'file-message';
    const title = document.createElement('div'); title.className = 'file-title';
    title.textContent = `▤  ${name}`; node.appendChild(title);
    const meta = document.createElement('div'); meta.className = 'file-meta';
    meta.textContent = `${sizeLabel(size)} · ${blob ? '可儲存到裝置' : '傳輸紀錄（重開後檔案需重傳）'}`;
    node.appendChild(meta);
    if (blob) {
      const url = URL.createObjectURL(blob);
      if (mime && ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/heic'].includes(mime.toLowerCase())) {
        const preview = document.createElement('img'); preview.className = 'file-photo';
        preview.src = url; preview.alt = `圖片預覽：${name}`; node.appendChild(preview);
      }
      const actions = document.createElement('div'); actions.className = 'file-actions';
      const save = document.createElement('button'); save.textContent = '下載 / 儲存檔案';
      save.onclick = () => {
        const a = document.createElement('a'); a.href = url; a.download = name; a.click();
        toast('請在 iPhone 的下載項目或檔案 App 查看');
      };
      actions.appendChild(save);
      const share = document.createElement('button'); share.textContent = '分享 / 存到檔案';
      share.onclick = async () => {
        try {
          const file = new File([blob], name, { type: mime || 'application/octet-stream' });
          if (!navigator.share || !navigator.canShare?.({ files: [file] })) throw new Error('unsupported');
          await navigator.share({ files: [file], title: name });
        } catch (error) {
          if (error.name !== 'AbortError') toast('此瀏覽器不支援檔案分享，請用下載按鈕');
        }
      };
      actions.appendChild(share);
      node.appendChild(actions);
    }
    group.appendChild(node);
    $('messages').scrollTop = $('messages').scrollHeight;
    if (remember) keepHistory({ kind: 'file', who, name, size, mine });
  }
  function beginFile(p) {
    if (!/^[a-zA-Z0-9_-]{4,75}$/.test(p.id) || !Number.isInteger(p.size) || p.size > MAX_FILE || p.size < 0) return;
    transfers.set(p.id, { name: p.name, size: p.size, from: p.from, mime: p.mime,
                          parts: [], got: 0, seq: 0 });
    toast(`正在接收：${p.name}`);
    updateProgress(p.id, p.name, 0, p.size, 'receive');
  }
  function appendChunk(p) {
    const state = transfers.get(p.id);
    if (!state || p.seq !== state.seq || typeof p.data !== 'string') {
      transfers.delete(p.id); finishProgress(p.id, '檔案分段不完整', false); return;
    }
    try {
      const binary = atob(p.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; ++i) bytes[i] = binary.charCodeAt(i);
      if (state.got + bytes.length > state.size) throw new Error('overflow');
      state.parts.push(bytes);
      state.got += bytes.length;
      state.seq++;
      updateProgress(p.id, state.name, state.got, state.size, 'receive');
    } catch (_) { transfers.delete(p.id); finishProgress(p.id, '檔案傳輸中斷', false); toast('檔案傳輸中斷'); }
  }
  function finishFile(p) {
    const state = transfers.get(p.id);
    transfers.delete(p.id);
    if (!state || state.got !== state.size) { finishProgress(p.id, '檔案接收不完整', false); toast('檔案資料不完整，請重新傳送'); return; }
    const blob = new Blob(state.parts, { type: state.mime || 'application/octet-stream' });
    showFileMessage(state.from || 'Windows', state.name, state.size, false, blob, state.mime);
    toast(`已收到 ${state.name}，點選儲存`);
    finishProgress(p.id, `接收完成：${state.name}`);
  }
  async function sendFiles(files) {
    if (!canSend()) return;
    if (sendingFiles) { toast('正在傳檔中，請等候目前選取的檔案送出'); return; }
    sendingFiles = true;
    $('fileBtn').disabled = true;
    const connection = ws;
    try {
    for (const file of Array.from(files)) {
      if (file.size > MAX_FILE) { toast(`${file.name} 超過 20 MB，請改用較小檔案`); continue; }
      const id = crypto.randomUUID().replaceAll('-', '');
      const type = file.type || 'application/octet-stream';
      const start = { type: 'file_start', id, name: file.name, mime: type, size: file.size };
      uploads.set(id, {file, mime: type, failed: false});
      updateProgress(id, file.name, 0, file.size, 'send');
      try {
        if (connection !== ws || connection.readyState !== WebSocket.OPEN) throw new Error('disconnect');
        connection.send(JSON.stringify(start));
        let seq = 0;
        for (let offset = 0; offset < file.size; offset += CHUNK) {
          while (connection.readyState === WebSocket.OPEN && connection.bufferedAmount > 400_000) {
            await new Promise(resolve => setTimeout(resolve, 25));
          }
          if (connection !== ws || connection.readyState !== WebSocket.OPEN || uploads.get(id)?.failed) throw new Error('disconnect');
          const bytes = new Uint8Array(await file.slice(offset, offset + CHUNK).arrayBuffer());
          if (connection !== ws || connection.readyState !== WebSocket.OPEN || uploads.get(id)?.failed) throw new Error('disconnect');
          const bin = String.fromCharCode(...bytes);
          connection.send(JSON.stringify({ type: 'file_chunk', id, seq, data: btoa(bin) }));
          seq++;
          updateProgress(id, file.name, Math.min(file.size, offset + bytes.length), file.size, 'send');
        }
        if (connection !== ws || connection.readyState !== WebSocket.OPEN || uploads.get(id)?.failed) throw new Error('disconnect');
        updateProgress(id, file.name, file.size, file.size, 'send', true);
        connection.send(JSON.stringify({ type: 'file_end', id }));
      } catch (_) { finishProgress(id, `未完成：${file.name}`, false); uploads.delete(id); toast(`傳送 ${file.name} 失敗，請重新傳送`); break; }
    }
    } finally {
      sendingFiles = false;
      $('fileBtn').disabled = false;
    }
    $('fileInput').value = '';
  }
  function initEvents() {
    $('sendClipboardBtn').addEventListener('click', async () => {
      if (!canSend()) return;
      try {
        const text = await navigator.clipboard.readText();
        if (!text) { toast('請先複製文字或網址'); return; }
        sendClipboard(text);
      } catch (_) {
        toast('請長按剪貼簿輸入框，選擇「貼上」後即會同步到電腦');
        $('clipboardInput').focus();
      }
    });
    $('receiveClipboardBtn').addEventListener('click', async () => {
      if (!remoteClipboard) return;
      try {
        await navigator.clipboard.writeText(remoteClipboard);
        $('clipboardStatus').textContent = '已存入手機剪貼簿，現在可以到其他 App 貼上。';
        toast('已複製電腦內容，可以直接貼上');
      } catch (_) { toast('無法寫入剪貼簿，請保持 Safari 在前景並再點一次'); }
    });
    $('clipboardInput').addEventListener('paste', event => {
      const text = event.clipboardData?.getData('text/plain');
      if (text) { event.preventDefault(); if (sendClipboard(text)) $('clipboardInput').value = ''; }
    });
    document.addEventListener('copy', () => {
      const text = window.getSelection()?.toString();
      if (paired && peerOnline && text) sendClipboard(text);
    });
    $('pairForm').addEventListener('submit', async event => {
      event.preventDefault();
      const code=$('pin').value.trim().replaceAll(' ','');
      if (!/^\d{8}$/.test(code)) { $('pairError').textContent='請輸入電腦畫面上的 8 位數配對碼。'; return; }
      if(pairBusy||lookingUp)return;
      window.AmosScanner.stop();
      lookingUp=true;
      $('pairError').textContent='正在尋找電腦；免費服務首次喚醒可能需要約一分鐘…';
      $('pairSubmit').disabled=true;
      try {
        const entry=await connection.usePin(code);
        if(entry.resumed){showRoom(entry.user);connect();}
        else await claimPair(entry.code);
      } catch(error){$('pairError').textContent=error.message || '無法連線，請稍後重試。';}
      finally{lookingUp=false;$('pairSubmit').disabled=false;}
    });
    $('scanBtn').addEventListener('click',()=>{if(!pairBusy&&!lookingUp)window.AmosScanner.start(acceptLink);});
    $('closeScanner').addEventListener('click',()=>window.AmosScanner.stop());
    $('reconnectBtn').addEventListener('click',()=>{if(ws){const old=ws;ws=null;old.close();}loadApp();});
    $('sendBtn').addEventListener('click', sendText);
    $('messageInput').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !/iPhone|iPad/.test(navigator.userAgent)) {
        event.preventDefault(); sendText();
      }
    });
    $('messageInput').addEventListener('input', () => {
      const item = $('messageInput'); item.style.height = 'auto';
      item.style.height = Math.min(item.scrollHeight, 115) + 'px';
    });
    $('messageInput').addEventListener('paste', event => {
      const files = event.clipboardData?.files;
      if (files && files.length) { event.preventDefault(); sendFiles(files); }
    });
    $('fileBtn').addEventListener('click', () => $('fileInput').click());
    $('fileInput').addEventListener('change', event => sendFiles(event.target.files));
    $('pasteBtn').addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (!text) { toast('剪貼簿沒有文字'); return; }
        $('messageInput').value += text;
        $('messageInput').focus();
      } catch (_) { toast('iPhone 請長按輸入框，選擇「貼上」'); $('messageInput').focus(); }
    });
    $('closeInstall').addEventListener('click', () => {
      $('installNote').hidden = true; sessionStorage.setItem('hide_install', 'yes');
    });
    $('unpairBtn').addEventListener('click', async () => {
      if (!confirm('確定取消這台手機與 Windows 電腦的配對？')) return;
      clearTimeout(retryTimer); paired = false;
      if (ws) ws.close();
      try { await connection.request('/api/logout', { method: 'POST' }); } catch (_) {}
      connection.forget(); showPair(); toast('已取消配對');
    });
    document.addEventListener('visibilitychange', async () => {
      if (document.visibilityState === 'visible' && paired && (!ws || ws.readyState > WebSocket.OPEN)) {
        const me = await getMe();
        if (me?.paired) connect(); else if (me && !me.paired) { connection.forget(); showPair(); } else scheduleReconnect();
      }
    });
  }
  initEvents();
  loadApp();
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
})();
