import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'

const require = createRequire(import.meta.url)
const { build } = require('esbuild')
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || 'playwright')
const app = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-drafts-browser-'))
const source = `
import React from 'react'
import {createRoot} from 'react-dom/client'
import './src/preload/index'
import Email from './src/renderer/src/views/Email'
import {ThreadProvider} from './src/renderer/src/store/thread'
const baseline=()=>({id:'gmail:synthetic-mailbox:draft-1',mailbox_id:'synthetic-mailbox',status:'draft',to:'recipient@example.test',subject:'Synthetic reply',body:'Original body',body_format:'plain',thread_id:'<source@example.test>'})
let draft=baseline(),present=true,authorized=true,transmissions=0,firstSend=true,failTransport=false,rejected=false
const calls=[]
window.fixtureRpc={invoke:async(channel,method,params)=>{
 calls.push({method,params})
 if(method==='mailboxes.list')return {mailboxes:[]}
 if(method==='emails.list_inbox')return {threads:[]}
 if(method==='drafts.list'){
  if(!authorized)throw Error('gmail_authorization_required')
  return present?[{...draft}]:[]
 }
 if(method==='drafts.get')return present?{ok:true,draft:{...draft}}:{ok:false,cause:'This draft was sent or deleted in Gmail.'}
 if(method==='drafts.update'){
  if(!present)throw Error('missing draft')
  const {draft_id,...patch}=params;draft={...draft,...patch};return {ok:true,draft:{...draft}}
 }
 if(method==='drafts.send'){
  if(rejected){rejected=false;return {ok:false,state:'held',effect_certainty:'not-dispatched',cause:'Correct the recipient before sending.'}}
  if(failTransport){failTransport=false;throw Error('Connection interrupted')}
  if(firstSend){firstSend=false;present=false;transmissions++;return {ok:false,state:'unconfirmed',draft_id:params.draft_id,request_key:params.request_key}}
  present=false;return {ok:true,state:'sent',draft_id:params.draft_id,request_key:params.request_key,message_id:'<sent@example.test>'}
 }
 if(method==='drafts.trash'){present=false;return {ok:true,state:'trashed',draft_id:params.draft_id,request_key:params.request_key}}
 throw Error('unexpected RPC: '+method)
}}
const root=createRoot(document.getElementById('root'))
let generation=0
const render=()=>root.render(<ThreadProvider><Email key={generation}/></ThreadProvider>)
window.fixture={calls:()=>calls,transmissions:()=>transmissions,
 externalEdit:()=>{draft={...draft,to:'edited@example.test',body:'Saved in Gmail'}},
 reset:()=>{draft=baseline();present=true;firstSend=true;generation++;render()},
 remount:()=>{generation++;render()},
 missing:()=>{present=false},
 attach:()=>{draft={...draft,attachments:[{filename:'synthetic.pdf'}]}},
 auth:value=>{authorized=value},failTransport:()=>{failTransport=true},reject:()=>{rejected=true}}
render()
`
await build({ stdin: { contents: source, resolveDir: app, sourcefile: 'mailbox-drafts-fixture.tsx', loader: 'tsx' },
  bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', outfile: join(output,'preview.js'),
  plugins: [{ name:'electron-fixture',setup(builder) {
    builder.onResolve({filter:/^electron$/},args=>({path:args.path,namespace:'fixture'}))
    builder.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:
      `export const ipcRenderer={on(){},invoke:(...args)=>window.fixtureRpc.invoke(...args)};export const contextBridge={exposeInMainWorld:(name,value)=>window[name]=value}`,loader:'js'}))
  }}] })
writeFileSync(join(output,'index.html'),'<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div><script src="preview.js"></script></body></html>')
const server=createServer((req,res)=>{
  const filename=req.url==='/'?'index.html':req.url.slice(1)
  if(!['index.html','preview.js'].includes(filename)){res.writeHead(404);res.end();return}
  res.setHeader('Content-Type',filename.endsWith('.js')?'text/javascript':'text/html')
  res.end(readFileSync(join(output,filename)))
})
await new Promise(done=>server.listen(0,'127.0.0.1',done))
const browser=await chromium.launch({headless:true,executablePath:process.env.MRCALL_BROWSER_BINARY,args:['--no-sandbox']})
try {
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  const base=`http://127.0.0.1:${server.address().port}`
  await page.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort())
  await page.goto(base)
  const folder=async()=>{
    await page.getByRole('button',{name:'Switch folder',exact:true}).click()
    await page.getByRole('menuitem',{name:/Drafts/}).click()
    await page.getByRole('button',{name:'Refresh drafts',exact:true}).waitFor()
  }
  const open=async()=>page.locator('[data-draft-id]').first().click()
  await folder()
  await page.evaluate(()=>window.fixture.externalEdit())
  await open()
  await page.getByText('Saved in Gmail',{exact:true}).waitFor()
  await page.getByText('edited@example.test',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Edit draft',exact:true}).click()
  await page.getByLabel('Draft subject',{exact:true}).fill('Edited in Desktop')
  await page.getByRole('button',{name:'Save draft',exact:true}).click()
  await page.getByRole('heading',{name:'Edited in Desktop',exact:true}).waitFor()
  const updates=await page.evaluate(()=>window.fixture.calls().filter(row=>row.method==='drafts.update'))
  assert.deepEqual(updates[0].params,{draft_id:'gmail:synthetic-mailbox:draft-1',subject:'Edited in Desktop'})
  await page.getByRole('button',{name:'Send draft',exact:true}).click()
  await page.getByRole('button',{name:'Check send',exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'Edit draft',exact:true}).isDisabled(),true)
  const first=await page.evaluate(()=>window.fixture.calls().find(row=>row.method==='drafts.send').params)
  await page.evaluate(()=>window.fixture.remount())
  await folder()
  assert.equal(await page.locator('[data-draft-id]').count(),0)
  await page.getByRole('button',{name:'Review pending send',exact:true}).click()
  await page.getByRole('button',{name:'Check send',exact:true}).click()
  await page.getByText('Sent. Confirmed in Sent mail.',{exact:true}).waitFor()
  const sends=await page.evaluate(()=>window.fixture.calls().filter(row=>row.method==='drafts.send'))
  assert.deepEqual(sends[1].params,first)
  assert.equal(await page.evaluate(()=>window.fixture.transmissions()),1)
  assert.equal(await page.locator('[data-draft-id]').count(),0)
  await page.evaluate(()=>window.fixture.reset())
  await folder();await page.evaluate(()=>window.fixture.missing());await open()
  await page.getByRole('alert').filter({hasText:'sent or deleted in Gmail'}).waitFor()
  assert.equal(await page.getByRole('button',{name:'Send draft',exact:true}).count(),0)
  assert.equal((await page.evaluate(()=>window.fixture.calls().filter(row=>row.method==='drafts.send'))).length,2)
  await page.evaluate(()=>window.fixture.reset())
  await folder();await page.evaluate(()=>window.fixture.attach());await open()
  assert.equal(await page.getByRole('button',{name:'Send draft',exact:true}).isDisabled(),true)
  assert.equal(await page.getByRole('button',{name:'Edit draft',exact:true}).isDisabled(),true)
  await page.getByRole('button',{name:'Move to Trash',exact:true}).click()
  await page.getByText('Moved to Trash.',{exact:true}).waitFor()
  assert.equal(await page.locator('[data-draft-id]').count(),0)
  await page.evaluate(()=>{window.fixture.reset();window.fixture.auth(false)})
  await folder()
  await page.getByRole('alert').filter({hasText:'Connect this mailbox to Gmail'}).waitFor()
  await page.evaluate(()=>window.fixture.auth(true))
  await page.getByRole('button',{name:'Refresh drafts',exact:true}).click()
  await page.locator('[data-draft-id]').first().waitFor()
  assert.equal(await page.getByRole('alert').count(),0)
  await open()
  await page.evaluate(()=>window.fixture.reject())
  await page.getByRole('button',{name:'Send draft',exact:true}).click()
  await page.getByText('Correct the recipient before sending.',{exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'Edit draft',exact:true}).isEnabled(),true)
  await page.evaluate(()=>window.fixture.failTransport())
  await page.getByRole('button',{name:'Send draft',exact:true}).click()
  await page.getByText('Connection interrupted',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Check send',exact:true}).click()
  await page.getByText('Sending is not confirmed. Check again to retrieve the result of the same send.',{exact:true}).waitFor()
  await page.getByRole('button',{name:'Check send',exact:true}).click()
  await page.getByText('Sent. Confirmed in Sent mail.',{exact:true}).waitFor()
  const retryKeys=await page.evaluate(()=>window.fixture.calls().filter(row=>row.method==='drafts.send').slice(-3).map(row=>row.params.request_key))
  assert.equal(new Set(retryKeys).size,1)
  assert.equal(await page.evaluate(()=>window.fixture.transmissions()),2)
  assert.deepEqual(errors,[])
  console.log('PASS: actual Email view and preload in Chromium: mailbox list/open, Gmail edit readback, sparse save, uncertain send key across remount, one simulated transmission per request, external removal without replacement, attachment preservation, Trash, authorization recovery, definite refusal and transport-loss retry. Provider/RPC are synthetic. Artifacts:',output)
} finally {
  await browser.close()
  await new Promise(done=>server.close(done))
}
