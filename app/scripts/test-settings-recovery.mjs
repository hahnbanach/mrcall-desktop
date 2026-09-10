import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'node:http'
import {execFileSync} from 'node:child_process'
const require=createRequire(import.meta.url)
const {build}=require('esbuild')
const app=resolve(fileURLToPath(new URL('..',import.meta.url)))
const output=mkdtempSync(join(tmpdir(),'mrcall-settings-recovery-'))
await build({entryPoints:[join(app,'scripts/fixtures-settings-preview.tsx')],bundle:true,platform:'browser',format:'iife',jsx:'automatic',outfile:join(output,'preview.js'),plugins:[{
  name:'offline-settings-boundaries',setup(build){
    build.onResolve({filter:/^(\.\.\/App|\.\.\/firebase\/(config|authUtils)|\.\/Connect(GoogleCalendar|WhatsApp))$/},args=>({path:args.path,namespace:'fixture'}))
    build.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:args.path.endsWith('/App')?'export const performSignOut=()=>{}':args.path.endsWith('/config')?"export const auth={currentUser:{uid:'fixture',email:'fixture@example.test'}}":args.path.endsWith('/authUtils')?'export const ensureEngineSession=async()=>true':'export default function Integration(){return null}',loader:'js'}))
  }
}]})
execFileSync(process.execPath,[join(app,'node_modules/tailwindcss/lib/cli.js'),'-i',join(app,'src/renderer/src/index.css'),'-o',join(output,'style.css')],{cwd:app,stdio:'pipe'})
writeFileSync(join(output,'index.html'),'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body><div id="root"></div><script src="preview.js"></script></body></html>')
const server=createServer((req,res)=>{const name=req.url.split('?')[0];if(!['/','/index.html','/preview.js','/style.css'].includes(name)){res.writeHead(404);res.end();return}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(join(output,name==='/'?'index.html':name.slice(1))))})
await new Promise(done=>server.listen(0,'127.0.0.1',done))
const {chromium}=require(process.env.MRCALL_PLAYWRIGHT_MODULE || 'playwright')
const browser=await chromium.launch({headless:true,executablePath:process.env.MRCALL_BROWSER_BINARY,args:['--no-sandbox']})
try{
 const page=await browser.newPage({viewport:{width:1200,height:950}})
 const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/*',route=>route.request().url().startsWith(`http://127.0.0.1:${server.address().port}`)?route.continue():route.abort())
 const base=`http://127.0.0.1:${server.address().port}`
 await page.goto(base+'/?state=cold')
 await page.getByText('Where does the engine run?',{exact:true}).waitFor()
 assert.equal(await page.getByText('Loading engine settings… Backend connection controls remain available below.',{exact:true}).isVisible(),true)
 await page.screenshot({path:join(output,'cold.png'),fullPage:true})
 await page.goto(base)
 const field=page.locator('#field-FIRST_NAME');await field.waitFor()
 assert.equal(await field.inputValue(),'Local Owner')
 await field.fill('Unsaved Local Edit')
 assert.equal(await page.getByRole('button',{name:'Save (1)',exact:true}).isEnabled(),true)
 await page.evaluate(()=>window.fixture.reconnect())
 await page.getByRole('button',{name:'Discard edits and reload settings',exact:true}).waitFor()
 assert.equal(await field.inputValue(),'Unsaved Local Edit')
 assert.equal(await page.getByRole('button',{name:'Save (1)',exact:true}).isDisabled(),true)
 assert.equal(await page.evaluate(()=>window.fixture.writes()),0)
 await page.screenshot({path:join(output,'dirty-reconnect.png'),fullPage:true})
 await page.getByRole('button',{name:'Discard edits and reload settings',exact:true}).click()
 await page.waitForFunction(()=>document.querySelector('#field-FIRST_NAME')?.value==='Remote Owner')
 assert.equal(await page.getByRole('button',{name:'Save',exact:true}).last().isDisabled(),true)
 assert.equal(await page.evaluate(()=>window.fixture.writes()),0)
 await page.waitForFunction(()=>document.querySelectorAll('input[name="backend-location"]')[1]?.checked)
 await page.screenshot({path:join(output,'reloaded.png'),fullPage:true})
 assert.deepEqual(errors,[])
 console.log('Settings cold/reconnect/discard browser checks passed:',output)
}finally{await browser.close();await new Promise(done=>server.close(done))}
