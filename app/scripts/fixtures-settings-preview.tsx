import React from 'react'
import {createRoot} from 'react-dom/client'
import Settings from '../src/renderer/src/views/Settings'
let cold = new URLSearchParams(location.search).get('state') === 'cold'
let backend = {location: 'local', url: ''}
let display = 'Local Owner'
let writes = 0
const listeners = new Set<(event: unknown) => void>()
const values = async () => {
  if (cold) return await new Promise<never>(() => {})
  return {values: {FIRST_NAME: display}}
}
Object.assign(window, {
  fixture: {
    reconnect: () => {backend = {location:'remote',url:'wss://fixture.example.test'}; display = 'Remote Owner'; for (const fn of listeners) fn({alive:false}); for(const fn of listeners) fn({alive:true,ready:true})},
    writes: () => writes
  },
  zylch: {
    settings: {getBackendLocation:async()=>backend,schema:async()=>({fields:[{key:'FIRST_NAME',label:'First name',type:'text',group:'Personal data',optional:true}]}),get:values,getSecret:async()=>({value:''}),update:async()=>{writes++;return {ok:true,applied:['FIRST_NAME']}},testBackendConnection:async()=>({ok:false,message:'Offline fixture',code:'offline'}),setBackendLocation:async()=>({ok:true})},
    onSidecarStatus:(fn:(event:unknown)=>void)=>{listeners.add(fn);return()=>listeners.delete(fn)},
    memory:{status:async()=>({available:false,has_key:false,reason:'Not configured'})},
    sms:{getSender:async()=>({sender:''})},
    account:{balance:async()=>({balance_credits:0})},
    sidecar:{restart:async()=>({ok:true})}
  }
})
createRoot(document.getElementById('root')!).render(<Settings />)
