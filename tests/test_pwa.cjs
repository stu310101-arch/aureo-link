// User-flow tests of the shipped PWA code, using a small deterministic DOM/socket.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = {}; this.style = {};
    this.value = ''; this.textContent = ''; this.hidden = false; this.disabled = false;
    this.scrollHeight = 100; this.classList = {add(){}, remove(){}, toggle(){}};
  }
  appendChild(node) { node.parent = this; this.children.push(node); return node; }
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); }
  querySelector() { return null; }
  addEventListener(kind, handler) { this.listeners[kind] = handler; }
  async fire(kind, event = {}) { return this.listeners[kind]?.(event); }
  focus() {}
  click() { return this.fire('click'); }
}

async function main() {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  class Socket {
    static OPEN = 1; static CONNECTING = 0;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.packets = []; }
    send(data) { this.packets.push(JSON.parse(data)); }
  }
  let written = null;
  const context = {
    console, URLSearchParams, Uint8Array, Blob, crypto,
    URL: {createObjectURL: () => 'blob:synthetic-test'},
    WebSocket: Socket, history: {replaceState(){}},
    location: {protocol:'https:', host:'test.invalid', search:'',pathname:'/',href:'https://test.invalid/'},
    navigator: {userAgent:'iPhone', clipboard: {
      readText: async () => 'synthetic phone clipboard',
      writeText: async text => { written = text; },
    }},
    window: {getSelection: () => ({toString: () => 'selected text'}), AmosConnection:{socketUrl:()=> 'wss://test.invalid/ws/mobile',hello(){}}},
    document: {getElementById:get, createElement:tag=>new Element(tag),
      createTextNode:text=>({textContent:text}), addEventListener(){}},
    localStorage: {getItem:()=>null,setItem(){}}, sessionStorage: {getItem:()=>null,setItem(){}},
    setTimeout:()=>1, clearTimeout(){},
    atob:value=>Buffer.from(value,'base64').toString('latin1'),
    btoa:value=>Buffer.from(value,'latin1').toString('base64'),
  };
  let source = fs.readFileSync('pwa/app.js','utf8').replace(/\r\n/g, '\n');
  assert(source.includes('  initEvents();\n  loadApp();'));
  source = source.replace('  initEvents();\n  loadApp();', `
    globalThis.uiTest = {ready(){paired=true;peerOnline=true;}, connect,
      get socket(){return ws;}, get uploads(){return uploads;},
      beginFile,appendChunk,finishFile,sendFiles};
    initEvents();`);
  vm.runInNewContext(source, context);
  const app = context.uiTest;
  app.ready(); app.connect(); app.socket.onopen();
  await app.socket.onmessage({data: JSON.stringify({type:'welcome',online:true})});

  await get('sendClipboardBtn').click();
  assert.equal(app.socket.packets.at(-1).type,'clipboard');
  assert.equal(app.socket.packets.at(-1).text,'synthetic phone clipboard');
  await app.socket.onmessage({data:JSON.stringify({type:'clipboard',text:'synthetic PC clipboard'})});
  assert.equal(written,null,'phone clipboard must not be silently changed outside a gesture');
  await get('receiveClipboardBtn').click();
  assert.equal(written,'synthetic PC clipboard');

  app.beginFile({id:'receive1',name:'photo.png',size:6,from:'PC',mime:'image/png'});
  assert.match(get('transferList').children.at(-1).children[0].textContent,/正在接收.*0%/);
  app.appendChunk({id:'receive1',seq:0,data:'YWJj'});
  assert.match(get('transferList').children.at(-1).children[0].textContent,/50%/);
  app.appendChunk({id:'receive1',seq:1,data:'ZGVm'});
  app.finishFile({id:'receive1'});
  assert.match(get('transferList').children.at(-1).children[0].textContent,/接收完成/);

  const file = {name:'test.bin',size:6,type:'application/octet-stream',
    slice:()=>({arrayBuffer:async()=>new Uint8Array([1,2,3,4,5,6]).buffer})};
  await app.sendFiles([file]);
  const end = app.socket.packets.at(-1);
  assert.equal(end.type,'file_end');
  assert.match(get('transferList').children.at(-1).children[0].textContent,/等待中繼確認/);
  await app.socket.onmessage({data:JSON.stringify({type:'sent',id:end.id})});
  assert.match(get('transferList').children.at(-1).children[0].textContent,/已送出/);
  assert.equal(app.uploads.size,0);
  assert.equal(get('fileBtn').disabled,false);
  console.log('PWA: clipboard gestures, receive progress, send progress and confirmation passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
