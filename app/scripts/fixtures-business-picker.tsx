import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import {BusinessPicker} from '../src/renderer/src/views/Settings'
import {auth} from '../src/renderer/src/firebase/config'
import {invalidateAuthSession} from '../src/renderer/src/firebase/authUtils'

type Params = Record<string, string | number>
type Row = Record<string, string | number>
const params = new URLSearchParams(location.search)
let mode = params.get('mode') || 'normal'
const rows: Row[] = [
  {businessId:'11111111-1111-1111-1111-111111111111',companyName:'Company Match'},
  {businessId:'22222222-2222-2222-2222-222222222222',nickname:'Nickname Match'},
  {businessId:'33333333-3333-3333-3333-333333333333',name:'Personal Match'},
  {businessId:'44444444-4444-4444-4444-444444444444',surname:'Surname Match'}
]
const calls: {method:string,params:Params}[] = []
const changes: string[] = []
const listeners = new Set<(event:unknown)=>void>()
const pending: (()=>void)[] = []
let active = 0
let peak = 0
async function rpc(method:string, query:Params) {
  calls.push({method,params:query})
  active++
  peak = Math.max(peak,active)
  const startedMode = mode
  try {
    await Promise.resolve()
    if (startedMode === 'hold') await new Promise<void>(resolve=>pending.push(resolve))
    if (startedMode === 'reject') throw new Error('Synthetic transport failure')
    if (startedMode === 'auth') throw Object.assign(new Error('Synthetic auth failure'),{code:-32010})
    if (startedMode === 'malformed') return {businesses:null}
    if (['partial','partialempty'].includes(startedMode) && 'surname' in query) throw new Error('Synthetic partial failure')
    if (['empty','partialempty'].includes(startedMode)) return {businesses:[]}
    if (method === 'list' || startedMode === 'sole') return {businesses:[rows[0]]}
    if ('businessId' in query) return {businesses:rows.filter(row=>row.businessId===query.businessId)}
    if ('emailAddress' in query) return {businesses:[rows[0]]}
    const field = ['companyName','nickname','name','surname'].find(key=>key in query)!
    if (String(query[field]).includes('missing')) return {businesses:[]}
    const found = rows.filter(row=>field in row)
    return {businesses: startedMode === 'duplicates' ? [...found,rows[0]] : found}
  } finally {active--}
}
const root = createRoot(document.getElementById('root')!)
Object.assign(window, {
  fixture: {
    calls:()=>calls, changes:()=>changes, peak:()=>peak, active:()=>active,
    mode:(next:string)=>{mode=next}, release:()=>{pending.splice(0).forEach(resolve=>resolve())},
    transport:()=>{for(const fn of listeners) fn({alive:false,ready:false})},
    reconnect:()=>{for(const fn of listeners) fn({alive:true,ready:true})},
    auth:()=>{const mock=auth as unknown as {currentUser:unknown,emit:()=>void};mock.currentUser=null;mock.emit()},
    invalidate:()=>invalidateAuthSession(), unmount:()=>root.unmount(), listeners:()=>listeners.size
  },
  zylch:{mrcall:{listMyBusinesses:(query:Params)=>rpc('list',query),searchBusinesses:(query:Params)=>rpc('search',query)},
    onSidecarStatus:(fn:(event:unknown)=>void)=>{listeners.add(fn);return()=>listeners.delete(fn)}}
})
function Fixture() {
  const [value,setValue] = useState(params.get('value') || '')
  return <BusinessPicker id="fixture-picker" value={value} isDirty={changes.length>0}
    lookupTimeoutMs={Number(params.get('timeout') || 2000)}
    onChange={next=>{changes.push(next);setValue(next)}} />
}
root.render(<Fixture />)
