import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'

const require = createRequire(import.meta.url)
const { build } = require('esbuild')
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || 'playwright')
const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-auth-persistence-'))
// Only the provider's HTTP responses are synthetic. The default product config,
// SDK sign-in/refresh/restoration/sign-out, and Chromium IndexedDB are real.
const source = `
import {auth} from './src/renderer/src/firebase/config'
import {RefreshOnlyPersistence} from './src/renderer/src/firebase/refreshOnlyPersistence'
import {signInWithEmailAndPassword,signInWithCredential,GoogleAuthProvider,signOut} from 'firebase/auth'
let active='fixture-A', serial=0, refreshes=0
const token=uid=>'e30.'+btoa(JSON.stringify({sub:uid,user_id:uid,iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+3600,auth_time:Math.floor(Date.now()/1000),nonce:++serial,firebase:{sign_in_provider:'password'}}))+'.synthetic'
window.fetch=async(input,options)=>{
 const url=String(input), body=String(options?.body||'')
 let result
 if(url.includes('securetoken.googleapis.com')){
  active=decodeURIComponent(new URLSearchParams(body).get('refresh_token')).split(':')[1];refreshes++
  result={access_token:token(active),refresh_token:'refresh:'+active,expires_in:'3600',token_type:'Bearer',user_id:active}
 }else if(url.includes('accounts:lookup')) result={users:[{localId:active,email:active+'@example.test',emailVerified:true,passwordHash:'synthetic',providerUserInfo:[{providerId:'password',rawId:active+'@example.test',email:active+'@example.test'}]}]}
 else if(url.includes('accounts:signInWithPassword')||url.includes('accounts:signInWithIdp')) result={localId:active,idToken:token(active),refreshToken:'refresh:'+active,expiresIn:'3600',email:active+'@example.test',registered:true,providerId:url.includes('Idp')?'google.com':'password'}
 else if(url.includes('recaptchaConfig')) result={recaptchaEnforcementState:[]}
 else throw Error('Unexpected synthetic provider endpoint')
 return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json'}})
}
async function rows(write){
 const db=await new Promise((yes,no)=>{const req=indexedDB.open('firebaseLocalStorageDb');req.onsuccess=()=>yes(req.result);req.onerror=()=>no(Error('database open failed'))})
 try{return await new Promise((yes,no)=>{const tx=db.transaction('firebaseLocalStorage',write?'readwrite':'readonly'), store=tx.objectStore('firebaseLocalStorage'),req=store.getAll();let values
  req.onsuccess=()=>{values=req.result;if(write)write(store,values)};tx.oncomplete=()=>yes(values);tx.onerror=tx.onabort=()=>no(Error('database transaction failed'))})}finally{db.close()}
}
window.fixture={
 ready:()=>auth.authStateReady(),uid:()=>auth.currentUser?.uid||null,
 password:async()=>{active='fixture-A';await signInWithEmailAndPassword(auth,'fixture@example.test','synthetic-password')},
 google:async()=>{active='fixture-B';await signInWithCredential(auth,GoogleAuthProvider.credential('synthetic-google-id'))},
 renew:()=>auth.currentUser.getIdToken(true),logout:()=>signOut(auth),
 concurrentLogout:async()=>{const values=await rows(),row=values.find(row=>row.value?.uid);await Promise.all([new RefreshOnlyPersistence()._get(row.fbase_key),signOut(auth)])},
 counts:()=>({refreshes,serializedAccess:!!auth.currentUser?.toJSON().stsTokenManager.accessToken}),
 token:()=>auth.currentUser?.getIdToken(),
 snapshot:async()=>{const values=await rows(),raw=JSON.stringify(values),current=auth.currentUser?await auth.currentUser.getIdToken():null
  return {uids:values.filter(row=>row.value?.uid).map(row=>row.value.uid),tokenKeys:values.filter(row=>row.value?.stsTokenManager).map(row=>Object.keys(row.value.stsTokenManager)),hasCurrentToken:!!current&&raw.includes(current),hasSerializedBearer:raw.includes('\"accessToken\"')||raw.includes('\"idToken\"')}},
 legacy:()=>rows((store,values)=>{const row=values.find(row=>row.value?.uid);store.put({...row,value:{...auth.currentUser.toJSON(),idToken:'synthetic-legacy-alias',unknown:{accessToken:'synthetic-legacy-extra'}}})}),
 malformed:()=>rows((store)=>{store.put({fbase_key:'firebase:authUser:'+auth.app.options.apiKey+':'+auth.app.name,value:{uid:'foreign',emailVerified:true,isAnonymous:false,providerData:[],apiKey:'wrong-project',appName:auth.app.name,stsTokenManager:{refreshToken:'refresh:foreign',accessToken:'synthetic-old'}}})}),
 rejectWrite:async()=>{const p=new RefreshOnlyPersistence();try{await p._set('firebase:authUser:wrong:app',{uid:'foreign',stsTokenManager:{accessToken:'synthetic'}});return false}catch{return true}}
}
`
await build({stdin:{contents:source,resolveDir:root,sourcefile:'auth-persistence-fixture.ts',loader:'ts'},bundle:true,platform:'browser',format:'iife',outfile:join(output,'fixture.js')})
writeFileSync(join(output,'index.html'),'<!doctype html><script src="fixture.js"></script>')
const server=createServer((req,res)=>{
 const name=req.url==='/'?'index.html':req.url.slice(1)
 if(!['index.html','fixture.js'].includes(name)){res.writeHead(404);res.end();return}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':'text/html');res.end(readFileSync(join(output,name)))
})
await new Promise(done=>server.listen(0,'127.0.0.1',done))
const base=`http://127.0.0.1:${server.address().port}`
const launch=()=>chromium.launchPersistentContext(join(output,'partition-A'),{headless:true,executablePath:process.env.MRCALL_BROWSER_BINARY,args:['--no-sandbox']})
const load=async context=>{
 const page=await context.newPage()
 await page.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort())
 await page.goto(base);await page.evaluate(()=>window.fixture.ready());return page
}
const clean=async(page,uid)=>{
 const snapshot=await page.evaluate(()=>window.fixture.snapshot())
 assert.deepEqual(snapshot.uids,uid?[uid]:[])
 assert.ok(snapshot.tokenKeys.every(keys=>keys.length===1&&keys[0]==='refreshToken'))
 assert.equal(snapshot.hasCurrentToken,false)
 assert.equal(snapshot.hasSerializedBearer,false)
}
const files=dir=>readdirSync(dir).flatMap(name=>{const path=join(dir,name);return statSync(path).isDirectory()?files(path):[path]})
let context,other
try{
 context=await launch();let page=await load(context)
 assert.equal(await page.evaluate(()=>window.fixture.uid()),null)
 await page.evaluate(()=>window.fixture.password());await clean(page,'fixture-A')
 assert.equal((await page.evaluate(()=>window.fixture.counts())).serializedAccess,true)
 await page.evaluate(()=>window.fixture.renew());await clean(page,'fixture-A')
 const current=await page.evaluate(()=>window.fixture.token())
 await context.close();context=null
 assert.ok(files(join(output,'partition-A')).every(path=>!readFileSync(path).includes(Buffer.from(current))))
 context=await launch();page=await load(context)
 assert.equal(await page.evaluate(()=>window.fixture.uid()),'fixture-A')
 assert.equal((await page.evaluate(()=>window.fixture.counts())).refreshes,1)
 await clean(page,'fixture-A')
 other=await chromium.launchPersistentContext(join(output,'partition-B'),{headless:true,executablePath:process.env.MRCALL_BROWSER_BINARY,args:['--no-sandbox']})
 const independent=await load(other);await clean(independent,null)
 await independent.evaluate(()=>window.fixture.google());await clean(independent,'fixture-B')
 assert.equal(await page.evaluate(()=>window.fixture.uid()),'fixture-A')
 await page.evaluate(()=>window.fixture.legacy());await page.close();page=await load(context)
 assert.equal(await page.evaluate(()=>window.fixture.uid()),'fixture-A');await clean(page,'fixture-A')
 assert.equal(await page.evaluate(()=>window.fixture.rejectWrite()),true)
 await page.evaluate(()=>window.fixture.concurrentLogout());await clean(page,null)
 await page.close();page=await load(context);assert.equal(await page.evaluate(()=>window.fixture.uid()),null)
 await clean(independent,'fixture-B')
 await independent.evaluate(()=>window.fixture.logout());await clean(independent,null)
 await page.evaluate(()=>window.fixture.malformed());await page.close();page=await load(context)
 assert.equal(await page.evaluate(()=>window.fixture.uid()),null);await clean(page,null)
 console.log('PASS: default product Firebase config and installed SDK: password and Google credential sign-in, refresh-only IndexedDB, forced renewal, full Chromium process restart with automatic refresh, complete closed-profile current-ID-token scan, separate partition identity, legacy token filtering, malformed-state refusal and durable logout. Provider HTTP is synthetic. Artifacts:',output)
}finally{
 if(context)await context.close();if(other)await other.close();await new Promise(done=>server.close(done))
}
