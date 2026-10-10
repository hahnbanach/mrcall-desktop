import { useEffect, useRef } from 'react'
import { onAuthStateChanged } from 'firebase/auth'
import { auth } from '../firebase/config'
import { isAuthSessionActive, onAuthSessionInvalidated } from '../firebase/authUtils'
import { financeTransport } from '../finance'

export interface FinanceContextToken {
  epoch: number
  uid: string
  transport: string
}

export function useFinanceContext(onReset: () => void) {
  const epoch = useRef(0)
  const companyChanging = useRef(false)
  const reset = useRef(onReset)
  reset.current = onReset
  useEffect(() => {
    const invalidate = () => { epoch.current++; reset.current() }
    const beginCompanyChange = () => { companyChanging.current = true; invalidate() }
    const finishCompanyChange = () => { companyChanging.current = false; invalidate() }
    window.addEventListener('mrcall:company-changing', beginCompanyChange)
    window.addEventListener('mrcall:company-changed', finishCompanyChange)
    const offStatus = window.zylch.onSidecarStatus(invalidate)
    const offInvalidation = onAuthSessionInvalidated(invalidate)
    let uid = auth.currentUser?.uid
    const offAuth = onAuthStateChanged(auth, user => {
      if (uid !== user?.uid) { uid = user?.uid; invalidate() }
    })
    return () => { epoch.current++; offStatus(); offAuth(); offInvalidation(); window.removeEventListener('mrcall:company-changing', beginCompanyChange); window.removeEventListener('mrcall:company-changed', finishCompanyChange) }
  }, [])
  const current = (token: FinanceContextToken) => isAuthSessionActive() && !companyChanging.current && token.epoch === epoch.current && token.uid === auth.currentUser?.uid
  const capture = async (): Promise<FinanceContextToken> => {
    if (companyChanging.current) throw new Error('company_changed')
    if (!isAuthSessionActive()) throw new Error('identity_required')
    const version = epoch.current
    const uid = auth.currentUser?.uid
    if (!uid) throw new Error('identity_required')
    const [profile, location, session] = await Promise.all([
      window.zylch.profile.current(), window.zylch.settings.getBackendLocation(), window.zylch.account.whoAmI()
    ])
    const token = { epoch: version, uid, transport: financeTransport(location) }
    if (!current(token)) throw new Error('context_changed')
    if (profile.id !== uid || !session.signed_in || session.uid !== uid) throw new Error('identity_required')
    return token
  }
  const invalidate = () => { epoch.current++; reset.current() }
  return { capture, current, epoch, companyChanging, invalidate }
}
