import React from 'react'
import {createRoot} from 'react-dom/client'
import Settings from '../src/renderer/src/views/Settings'
let cold = new URLSearchParams(location.search).get('state') === 'cold'
let backend = {location: 'local', url: ''}
let display = 'Local Owner'
let writes = 0
let key = new URLSearchParams(location.search).get('state') === 'byok' ? '<set>' : ''
const opened: string[] = []
let failTopup = false
const listeners = new Set<(event: unknown) => void>()
const values = async () => {
  if (cold) return await new Promise<never>(() => {})
  return {values: {FIRST_NAME: display, ANTHROPIC_API_KEY: key, EMAIL_ADDRESS: 'owner@example.test'}}
}
const primaryMailbox = {id: 'mb-primary', address: 'owner@example.test', imap_host: 'imap.example.test', imap_port: 993, smtp_host: 'smtp.example.test', smtp_port: 587, preset: null, is_primary: true, configured: true, state: 'ok', last_sync_at: '2026-09-30T08:00:00', last_error: null, created_at: '2026-09-01T00:00:00'}
const pecPreset = {id: 'pec.net', label: 'PEC.net (Register.it)', domains: ['pec.net'], imap_host: 'imap.pec-email.com', imap_port: 993, imap_security: 'ssl', smtp_host: 'smtp.pec-email.com', smtp_port: 465, smtp_security: 'ssl', username: 'full_address', password_label: 'PEC mailbox password'}
const refused = {ok: false, status: 'auth', message: 'the server rejected the username or password'}
Object.assign(window, {
  fixture: {
    reconnect: () => {backend = {location:'remote',url:'wss://fixture.example.test'}; display = 'Remote Owner'; for (const fn of listeners) fn({alive:false}); for(const fn of listeners) fn({alive:true,ready:true})},
    writes: () => writes, opened: () => opened, failTopup: () => {failTopup = true}, savedKey: () => key
  },
  zylch: {
    settings: {getBackendLocation:async()=>backend,schema:async()=>({fields:[{key:'FIRST_NAME',label:'First name',type:'text',group:'Personal data',optional:true},{key:'ANTHROPIC_API_KEY',label:'Anthropic API key',type:'password',secret:true,group:'LLM',optional:true},{key:'EMAIL_ADDRESS',label:'Email address',type:'text',group:'Email',optional:true}]}),get:values,getSecret:async()=>({value:''}),update:async(changes:Record<string,string>)=>{writes++;if ('ANTHROPIC_API_KEY' in changes) key=changes.ANTHROPIC_API_KEY;return {ok:true,applied:Object.keys(changes)}},testBackendConnection:async()=>({ok:false,message:'Offline fixture',code:'offline'}),setBackendLocation:async()=>({ok:true})},
    onSidecarStatus:(fn:(event:unknown)=>void)=>{listeners.add(fn);return()=>listeners.delete(fn)},
    memory:{status:async()=>({available:false,has_key:false,reason:'Not configured'})},
    mailboxes:{list:async()=>({mailboxes:[primaryMailbox]}),presets:async()=>({presets:[pecPreset]}),test:async()=>refused,add:async()=>refused,update:async()=>refused,remove:async()=>({ok:false,status:'unknown',message:'no such mailbox on this profile'})},
    sms:{getSender:async()=>({sender:''})},
    account:{balance:async()=>({balance_credits:0,balance_usd:0})},
    shell:{openExternal:async(url:string)=>{opened.push(url);return {ok:!failTopup}}},
    sidecar:{restart:async()=>({ok:true})}
  }
})
createRoot(document.getElementById('root')!).render(<Settings />)
