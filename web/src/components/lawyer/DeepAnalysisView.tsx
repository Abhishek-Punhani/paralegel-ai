'use client'
import { useCallback, useEffect, useState } from 'react'
import { FileText, RefreshCw } from 'lucide-react'
import { FinalPacketView } from './FinalPacketView'
import { LawyerChat } from './LawyerChat'
import { StreamingEventsView, AnalysisEvent } from './StreamingEventsView'
import { BACKEND_URL, readResponse } from '@/lib/backend'

interface Session { backendSessionId: string; clientName?: string; shareLink?: string }

export function DeepAnalysisView({ session }: { session: Session }) {
  const [packet, setPacket] = useState<any>(null)
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const loadPacket = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/session/${session.backendSessionId}/packet`, { cache: 'no-store' })
      if (response.status === 404) return
      const data = await readResponse(response)
      setPacket(data.json || {})
      setMarkdown(data.markdown || null)
      setDone(true)
      setError('')
      if (session.shareLink) await fetch(`/api/sessions/${session.shareLink}/complete`, { method: 'POST' })
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to load packet') }
  }, [session.backendSessionId, session.shareLink])
  useEffect(() => { setPacket(null); setMarkdown(null); setDone(false); setError(''); void loadPacket() }, [loadPacket])
  const onEvent = useCallback((event: AnalysisEvent) => {
    if (['packet_ready', 'analysis_complete'].includes(event.event || '') || event.type === 'connected') void loadPacket()
    if (event.event === 'analysis_error') setError(event.error || 'Analysis failed. Return to intake review to retry.')
  }, [loadPacket])
  return <div className="h-full min-h-0 flex flex-col lg:flex-row overflow-hidden">
    <StreamingEventsView sessionId={session.backendSessionId} onEvent={onEvent} done={done} />
    <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-[#0b0d0e]">
      {error && <div role="alert" className="m-4 rounded-xl bg-red-500/10 border border-red-500/20 px-4 py-3 text-xs text-red-300 flex items-center gap-3"><span className="flex-1">{error}</span><button onClick={loadPacket} className="flex items-center gap-1"><RefreshCw className="h-3 w-3" />Retry</button></div>}
      {packet ? <><div className="flex-1 min-h-0 overflow-hidden"><FinalPacketView packet={packet} markdown={markdown} /></div><LawyerChat key={session.backendSessionId} sessionId={session.backendSessionId} backendUrl={BACKEND_URL} /></> : <div className="flex-1 flex flex-col items-center justify-center p-8 text-center"><FileText className="h-10 w-10 text-[#a8dab5]/25 mb-5" /><h2 className="text-lg font-medium">Building the case brief</h2><p className="text-sm text-zinc-500 max-w-sm leading-relaxed mt-3">The agents are reviewing the intake, researching authorities, and examining both sides. Your packet appears here when the analysis completes.</p><button onClick={loadPacket} className="text-xs text-zinc-400 mt-6 flex gap-2 items-center"><RefreshCw className="h-3 w-3" />Check for completed packet</button></div>}
    </div>
  </div>
}
