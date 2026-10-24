/* Persistent, fixed-origin mobile identity. No secrets are put in URLs. */
(() => {
  'use strict';
  const KEY = 'amos_link_mobile_v3';
  const DIRECTORY = 'https://amos-link-pairing-stu310101.onrender.com';
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (_) {}
  const validHex = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  if (!saved || !validHex(saved.token)) saved = null;
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

  function origin(value) {
    const url = new URL(value);
    const local = /^(localhost|127\.0\.0\.1)$/.test(url.hostname);
    if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password) throw new Error('請使用電腦提供的 HTTPS 連線網址。');
    return url.origin;
  }
  let relay='';
  try { if(saved)relay=origin(saved.relay); } catch(_){saved=null;}
  // A self-hosted relay remains usable; GitHub Pages starts without a relay.
  const selfHosted=location.hostname!=='stu310101-arch.github.io' && location.pathname==='/';
  if (!relay && selfHosted) relay = location.origin;

  function remember(value) {
    saved = value;
    if (value) localStorage.setItem(KEY, JSON.stringify(value));
    else localStorage.removeItem(KEY);
  }
  async function request(path, options = {}, timeout = 15000) {
    if (!relay) throw new Error('請先掃描 QR Code 或輸入 8 位數連線碼。');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = {...options.headers};
    if (saved?.token && saved.relay===relay) headers.Authorization = 'Bearer ' + saved.token;
    try {
      return await fetch(relay + path, {...options, headers, signal:controller.signal,
        credentials: relay === location.origin ? 'same-origin' : 'omit', cache:'no-store'});
    } finally { clearTimeout(timer); }
  }
  async function directory(path, timeout = 80000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(DIRECTORY + path, {cache:'no-store', signal:controller.signal, credentials:'omit'});
      if (response.status === 404) throw new Error('找不到在線電腦，請確認電腦程式已開啟，並使用目前顯示的連線碼。');
      if (response.status === 429) throw new Error('嘗試次數較多，請稍候一分鐘再試。');
      if (!response.ok) throw new Error('免費配對服務正在喚醒，請稍後再試。');
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  async function verifyRoute(entry, credential = saved) {
    if (!credential || entry.locator !== credential.locator || !validHex(credential.route_key) || !validHex(entry.proof)) return false;
    if (!Number.isInteger(entry.expires) || entry.expires < Date.now()/1000 - 20 || entry.expires > Date.now()/1000 + 330) return false;
    const target = origin(entry.url);
    const bytes = hex => Uint8Array.from(hex.match(/../g), part => parseInt(part, 16));
    const key = await crypto.subtle.importKey('raw', bytes(credential.route_key), {name:'HMAC',hash:'SHA-256'}, false, ['verify']);
    return crypto.subtle.verify('HMAC', key, bytes(entry.proof), new TextEncoder().encode(`${entry.locator}\n${target}\n${entry.expires}`));
  }
  async function refreshAddress() {
    if (!saved?.locator || !saved.route_key) return false;
    const entry = await directory('/v1/devices/' + saved.locator);
    if (!await verifyRoute(entry)) throw new Error('電腦位址驗證未通過，請重新掃描電腦畫面上的 QR Code。');
    relay = origin(entry.url);
    remember({...saved, relay});
    return true;
  }
  async function me() {
    try {
      const response = await request('/api/me', {}, 7000);
      if (response.ok) return await response.json();
    } catch (_) {}
    try {
      if (await refreshAddress()) {
        const response = await request('/api/me', {}, 10000);
        if (response.ok) return await response.json();
      }
    } catch (_) {}
    return null; // network failure never silently erases a trusted identity
  }
  function decode(value) {
    const url = new URL(value);
    const trustedEntry = url.origin === 'https://stu310101-arch.github.io' && url.pathname === '/aureo-link/phone/';
    const fragment = new URLSearchParams(url.hash.slice(1));
    if (trustedEntry && fragment.get('relay')) {
      return {relay:origin(fragment.get('relay')), pair:fragment.get('pair') || '', locator:fragment.get('locator') || ''};
    }
    if (url.searchParams.has('pair')) return {relay:origin(url.href), pair:url.searchParams.get('pair'), locator:''};
    throw new Error('這不是 Amos 電腦畫面上的配對 QR Code。');
  }
  async function useQr(value) {
    const entry = decode(value);
    if(saved && entry.locator && entry.locator!==saved.locator)throw new Error('已記住另一台電腦。請先取消配對，再連接新的電腦。');
    if (saved && entry.locator === saved.locator) {
      // A known device must prove the new address before seeing its token.
      if(saved.route_key && entry.relay!==saved.relay)await refreshAddress();
      else if(entry.relay!==saved.relay)throw new Error('請先取消舊配對再連接新的位址。');
      const response = await request('/api/me');
      const user = await response.json();
      if (user.paired) return {resumed:true, user};
    }
    relay = entry.relay;
    if (saved) remember(null);
    return {code:entry.pair, locator:entry.locator};
  }
  async function usePin(pin) {
    if(selfHosted && !saved)return {code:pin};
    const entry = await directory('/v1/pins/' + pin);
    if(saved && entry.locator!==saved.locator)throw new Error('已記住另一台電腦。請先取消配對，再連接新的電腦。');
    const same = saved && saved.locator === entry.locator;
    if (same) {
      if (!await verifyRoute(entry)) throw new Error('電腦位址驗證失敗，請使用 App 內相機重新掃碼。');
      relay = origin(entry.url);
      remember({...saved,relay});
      const response = await request('/api/me');
      const user = await response.json();
      if (user.paired) return {resumed:true,user};
    }
    relay = origin(entry.url);
    if (saved) remember(null);
    return {code:pin,locator:entry.locator};
  }
  function approved(result) {
    if (!result.token) return; // legacy same-origin cookie client
    if(!validHex(result.token))throw new Error('手機配對憑證格式不正確，請重新配對。');
    remember({token:result.token, relay, locator:result.locator || '',route_key:result.route_key || ''});
  }
  window.AmosConnection = {
    request, me, usePin, useQr, approved, refreshAddress, verifyRoute, decode,
    get saved(){return saved;}, get relay(){return relay;},
    socketUrl(){return relay.replace(/^http/,'ws') + '/ws/mobile';},
    hello(socket){if(saved?.token)socket.send(JSON.stringify({type:'mobile_hello',token:saved.token}));},
    forget(){remember(null);},
  };
})();
