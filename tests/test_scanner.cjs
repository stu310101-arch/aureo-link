const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const zlib=require('node:zlib');
const jsQR=require('../pwa/vendor/jsQR.js');
const fixture=JSON.parse(fs.readFileSync('tests/qr_fixture.json','utf8'));
const pixels=new Uint8ClampedArray(zlib.inflateSync(Buffer.from(fixture.rgba,'base64')));
assert.equal(jsQR(pixels,fixture.width,fixture.height).data,fixture.value,'decode the exact 188-pixel desktop QR format');
let resolveCamera,stopped=0,frames=0;
const nodes=new Map();
const get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',srcObject:null,play:async()=>{}});return nodes.get(id);};
const context={window:{},navigator:{mediaDevices:{getUserMedia:()=>new Promise(resolve=>resolveCamera=resolve)}},
  document:{getElementById:get,addEventListener(){}},requestAnimationFrame:()=>++frames,cancelAnimationFrame(){}};
vm.runInNewContext(fs.readFileSync('pwa/scanner.js','utf8'),context);
(async()=>{
  const pending=context.window.AmosScanner.start(()=>{});
  context.window.AmosScanner.stop(); // closed while system permission prompt is pending
  resolveCamera({getTracks:()=>[{stop:()=>stopped++}]});
  await pending;
  assert.equal(stopped,1);assert.equal(frames,0);assert(get('scanner').hidden);
  const manifest=JSON.parse(fs.readFileSync('pwa/manifest.webmanifest','utf8'));
  assert.equal(manifest.start_url,'./');assert.equal(manifest.scope,'./');
  const page=fs.readFileSync('pwa/index.html','utf8');
  assert(page.includes('id="scanBtn"')&&page.includes('playsinline muted'));
  assert(!/href="\//.test(page),'all assets must work below /aureo-link/phone/');
  console.log('PWA camera: desktop QR decodes, closing permission prompt stops camera, fixed install scope passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
