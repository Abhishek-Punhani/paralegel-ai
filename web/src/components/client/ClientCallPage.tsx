'use client'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Scale, ShieldCheck, FileText, AlertCircle } from 'lucide-react'
import { CallStage } from './CallStage'
import { ControlTray } from './ControlTray'
import { DocumentUploadModal } from './DocumentUploadModal'
import { useSarvamCall } from '@/hooks/useSarvamCall'
import { BACKEND_URL, readResponse } from '@/lib/backend'

interface SessionInfo { sessionId: string; lawyerName: string; lawyerContact?: string; status: string }

export function ClientCallSession() {
  const params = useSearchParams()
  const token = params.get('token') || params.get('session') || params.get('sessionId')
  const [info, setInfo] = useState<SessionInfo>()
  const [sessionError, setSessionError] = useState('')
  const [showDocuments, setShowDocuments] = useState(false)
  const [consent, setConsent] = useState(false)
  const [language, setLanguage] = useState('hi')
  const startedAt = useRef<number>()
  const callLogged = useRef(false)
  const starting = useRef(false)
  const [startingCall, setStartingCall] = useState(false)
  const [startError, setStartError] = useState('')
  const call = useSarvamCall(info?.sessionId, language)

  useEffect(() => {
    if (!token) { setSessionError('This consultation link is incomplete. Please request a new link from your advocate.'); return }
    const controller = new AbortController()
    fetch(`/api/sessions/${encodeURIComponent(token)}`, { signal: controller.signal }).then(async response => {
      return readResponse<SessionInfo>(response)
    }).then(setInfo).catch(cause => { if (!controller.signal.aborted) setSessionError(cause.message) })
    return () => controller.abort()
  }, [token, params])

  useEffect(() => { if (call.pendingDocs.length) setShowDocuments(true) }, [call.pendingDocs.length])
  useEffect(() => { call.pauseForDocument(showDocuments && call.pendingDocs.length > 0) }, [showDocuments, call.pendingDocs.length, call.pauseForDocument])
  useEffect(() => {
    if (call.callState !== 'ended' || !callLogged.current || !token) return
    callLogged.current = false
    void fetch(`/api/sessions/${token}/call-end`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: call.completed ? 'completed' : 'disconnected', duration: startedAt.current ? Math.round((Date.now() - startedAt.current) / 1000) : 0 }) })
  }, [call.callState, call.completed, token])
  const start = async () => {
    if (starting.current) return
    starting.current = true
    setStartingCall(true)
    setStartError('')
    startedAt.current = Date.now()
    try {
    if (token) {
      try {
        await readResponse(await fetch(`/api/sessions/${token}/call-start`, { method: 'POST' }))
        callLogged.current = true
      } catch (cause) { setStartError(cause instanceof Error ? cause.message : 'Could not start consultation'); return }
    }
    const connected = await call.start()
    if (!connected && token && callLogged.current) {
      callLogged.current = false
      void fetch(`/api/sessions/${token}/call-end`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'disconnected', duration: 0 }) })
    }
    } finally { starting.current = false; setStartingCall(false) }
  }
  const end = () => {
    call.end()
  }

  if (sessionError) return <main className="min-h-[100svh] bg-[#0b0d0e] flex items-center justify-center p-8"><div className="max-w-sm text-center"><AlertCircle className="mx-auto mb-5 h-10 w-10 text-amber-300" /><h1 className="text-xl font-semibold">Unable to open consultation</h1><p className="mt-3 text-sm text-zinc-400">{sessionError}</p></div></main>
  if (!info) return <main className="min-h-[100svh] bg-[#0b0d0e] grid place-items-center"><p className="animate-pulse text-sm text-zinc-400">Opening your consultation…</p></main>
  return <main className="h-[100svh] bg-[#0b0d0e] relative overflow-hidden flex flex-col text-zinc-100">
    <header className="absolute top-0 inset-x-0 z-10 flex items-center justify-between p-5 sm:p-7"><div className="flex items-center gap-3"><Scale className="h-5 w-5 text-[#a8dab5]" /><span className="font-semibold tracking-tight">NyayaLens</span></div><span className="text-[11px] text-zinc-400 flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Private intake</span></header>
    <CallStage callState={call.callState} volume={call.volume} speakingText={call.speakingText} />
    <div className="absolute top-20 inset-x-5 text-center"><p className="text-xs text-zinc-500">Consultation for {info.lawyerName}</p><p className="mt-2 text-[10px] tracking-[.18em] uppercase text-[#a8dab5]/70">Voice powered by Sarvam AI</p></div>
    <div className="absolute bottom-40 inset-x-5 mx-auto max-w-md text-center space-y-3">
      {(call.error || startError) && <p role="alert" className="text-xs text-amber-200 bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-3">{call.error || startError}</p>}
      {call.needsRetry && <div className="space-y-2"><p className="text-xs text-zinc-400">Your response is saved. Retry processing without repeating it.</p><button onClick={call.retryResponse} disabled={call.callState === 'thinking'} className="px-4 py-2 rounded-lg border border-[#a8dab5]/30 bg-[#a8dab5]/10 text-[#a8dab5] text-xs disabled:opacity-50">{call.callState === 'thinking' ? 'Retrying saved response…' : 'Retry saved response'}</button></div>}
      {(call.callState === 'idle' || call.callState === 'ended') && <><select aria-label="Interview language" value={language} onChange={e => setLanguage(e.target.value)} className="rounded-lg bg-[#141719] border border-white/10 px-3 py-2 text-xs"><option value="hi">Hindi / Hinglish</option><option value="en">English</option></select><label className="flex items-start justify-center gap-2 text-xs text-zinc-400 leading-relaxed"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} className="mt-1 accent-[#a8dab5]" />I agree to share my voice responses with my advocate for this case intake. Nyaya is an AI assistant.</label></>}
      {call.recording && <p className="text-xs text-zinc-400">Speak naturally. Pause when finished, or tap “Send response”.</p>}
      {call.pendingDocs.length > 0 && <button onClick={() => setShowDocuments(true)} className="text-xs text-[#a8dab5] inline-flex items-center gap-2"><FileText className="h-4 w-4" /> Upload requested documents ({call.pendingDocs.length})</button>}
    </div>
    <ControlTray callState={call.callState} muted={call.muted} volume={call.volume} onMuteToggle={call.toggleMute} onConnect={start} onDisconnect={end} disabled={!consent || startingCall} recording={call.recording} onSend={call.sendResponse} />
    {showDocuments && call.pendingDocs.length > 0 && <DocumentUploadModal pendingDocs={call.pendingDocs} sessionId={info.sessionId} backendUrl={BACKEND_URL} onDocUploaded={call.removeDocument} onClose={() => setShowDocuments(false)} />}
  </main>
}

export const ClientCallPage = ClientCallSession
