const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
const source=fs.readFileSync('pwa/connection.js','utf8');
const storage=new Map();
const calls=[];
const token='a'.repeat(64),routeKey='b'.repeat(64),locator='c'.repeat(64);
let current='https://first-test.trycloudflare.com';
let stale=false,forged=false;
function entry(){
  const expires=Math.floor(Date.now()/1000)+180;
  const proof=crypto.createHmac('sha256',Buffer.from(routeKey,'hex')).update(`${locator}\n${current}\n${expires}`).digest('hex');
  return {locator,url:current,expires,proof:forged?'0'.repeat(64):proof};
}
function app(){
  const context={URL,URLSearchParams,Uint8Array,TextEncoder,AbortController,Date,crypto:crypto.webcrypto,setTimeout,clearTimeout,
    location:new URL('https://stu310101-arch.github.io/aureo-link/phone/'),window:{},
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    fetch:async(url,options={})=>{
      calls.push({url,options});
      if(url.includes('/v1/pins/')||url.includes('/v1/devices/'))return {ok:true,status:200,json:async()=>entry()};
      if(stale&&url.startsWith('https://first-test.'))throw new Error('old tunnel removed');
      assert.equal(options.headers.Authorization,'Bearer '+token);
      return {ok:true,status:200,json:async()=>({paired:true,desktop_id:'test'})};
    }};
  vm.runInNewContext(source,context);
  return context.window.AmosConnection;
}
(async()=>{
  let connection=app();
  assert.equal(connection.saved,null);
  assert.equal((await connection.usePin('12345678')).code,'12345678');
  connection.approved({token,locator,route_key:routeKey});
  assert((await connection.me()).paired);
  connection=app(); // killed/reopened PWA; no previous JS state or cookies
  assert((await connection.me()).paired);
  stale=true;current='https://second-test.trycloudflare.com';
  assert((await connection.me()).paired,'resume after PC changes tunnel');
  assert.equal(connection.saved.relay,current);
  const packets=[];connection.hello({send:value=>packets.push(JSON.parse(value))});
  assert.equal(packets[0].token,token);
  assert(!connection.socketUrl().includes(token));
  assert(calls.every(item=>!item.url.includes(token)&&!item.url.includes(routeKey)));
  forged=true;current='https://forged-test.trycloudflare.com';
  await assert.rejects(connection.refreshAddress(),/驗證/);
  assert(!calls.some(item=>item.url.startsWith(current)),'never send phone token to a forged address');
  assert.throws(()=>connection.decode('https://evil.invalid/#relay=https://evil.invalid'),/不是/);
  const parsed=connection.decode('https://stu310101-arch.github.io/aureo-link/phone/#relay=https%3A%2F%2Fsecond-test.trycloudflare.com&pair='+ 'd'.repeat(48)+'&locator='+locator);
  assert.equal(parsed.relay,'https://second-test.trycloudflare.com');
  console.log('Fixed PWA: 8-digit lookup, killed/reopened app, changed tunnel, HMAC address verification and token secrecy passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
