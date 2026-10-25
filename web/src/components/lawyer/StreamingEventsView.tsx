'use client'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Loader2, AlertCircle, Activity } from 'lucide-react'
import { motion } from 'framer-motion'
import { BACKEND_URL } from '@/lib/backend'

export interface AnalysisEvent { id?: string; event?: string; kind?: string; status?: string; content?: { message?: string; summary?: string; agent?: string }; message?: string; error?: string; type?: string }

export function StreamingEventsView({ sessionId, onEvent, done }: { sessionId: string; onEvent: (event: AnalysisEvent) => void; done: boolean }) {
  const [events, setEvents] = useState<AnalysisEvent[]>([])
  const [connection, setConnection] = useState('Connecting')
  const seen = useRef(new Set<string>())
  const scroll = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const callback = useRef(onEvent)
  callback.current = onEvent
  useEffect(() => {
    setEvents([])
    seen.current.clear()
    const source = new EventSource(`${BACKEND_URL}/api/notifications/analysis/stream?session_id=${encodeURIComponent(sessionId)}`)
    source.onopen = () => { setConnection('Live'); callback.current({ type: 'connected' }) }
    source.onerror = () => setConnection('Reconnecting…')
    source.onmessage = message => {
      try {
        const payload: AnalysisEvent = JSON.parse(message.data)
        if (payload.type === 'heartbeat' || payload.type === 'connected') return
        const id = payload.id || message.lastEventId
        if (id && seen.current.has(id)) return
        if (id) seen.current.add(id)
        if (payload.kind || payload.event === 'analysis_error') setEvents(previous => [...previous.slice(-199), payload])
        callback.current(payload)
        if (payload.event === 'analysis_complete') { setConnection('Complete'); source.close() }
      } catch { setConnection('Unable to read a progress update') }
    }
    return () => source.close()
  }, [sessionId])
  useEffect(() => {
    if (follow.current) scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' })
  }, [events])
  return <aside className="flex flex-col min-h-0 bg-[#111517] border-b lg:border-b-0 lg:border-r border-white/[.07] w-full lg:w-80 shrink-0 max-h-64 lg:max-h-none">
    <header className="px-5 py-4 border-b border-white/[.07] flex items-center gap-2.5"><Activity className="h-4 w-4 text-[#a8dab5]" /><h3 className="text-sm font-medium">Analysis activity</h3><span className="ml-auto text-[10px] text-zinc-500">{done ? 'Complete' : connection}</span></header>
    <div ref={scroll} onScroll={event => { const node = event.currentTarget; follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 50 }} className="flex-1 overflow-y-auto p-5 space-y-6">
      {events.length === 0 && <p className="text-xs text-zinc-500 leading-relaxed">{done ? 'The completed packet is ready for review.' : 'Waiting for the analysis agents. Progress updates appear here as each step runs.'}</p>}
      {events.map((event, index) => <EventMessage key={event.id || index} event={event} />)}
    </div>
    <p className="px-5 py-3 border-t border-white/[.05] text-[10px] text-zinc-600">Live task status and research results</p>
  </aside>
}

export function EventMessage({ event }: { event: AnalysisEvent }) {
  const failed = event.event === 'analysis_error' || event.status === 'error'
  const complete = ['completed', 'done'].includes(event.status || '')
  const Icon = failed ? AlertCircle : complete ? CheckCircle2 : Loader2
  const message = event.content?.message || event.content?.summary || event.message || event.error || event.event?.replace(/_/g, ' ')
  return <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex items-start gap-3"><Icon className={`h-4 w-4 shrink-0 mt-.5 ${failed ? 'text-red-400' : complete ? 'text-[#a8dab5]' : 'text-purple-300 animate-spin'}`} /><div><p className="text-xs leading-relaxed text-zinc-300">{message}</p>{event.content?.agent && <p className="text-[10px] mt-1.5 text-zinc-600 capitalize">{event.content.agent.replace(/_/g, ' ')}</p>}</div></motion.div>
}
