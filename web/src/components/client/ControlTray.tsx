'use client'
import { Mic, MicOff, PhoneOff, Phone, Send } from 'lucide-react'
import { motion } from 'framer-motion'
import type { CallState } from '@/hooks/useSarvamCall'

export function AudioPulse({ active, volume = 0 }: { active: boolean; volume?: number }) {
  return <div aria-hidden="true" className="flex h-7 items-center gap-1">{[.5, .8, 1, .7, .4].map((scale, i) => <motion.span key={i} className="w-1 rounded-full bg-[#a8dab5]" animate={{ height: active ? [6, 10 + scale * 14, 6] : 4 + volume * scale * 24 }} transition={active ? { duration: .7, repeat: Infinity, delay: i * .1 } : { duration: .1 }} />)}</div>
}

interface Props {
  callState: CallState; muted: boolean; volume: number; recording: boolean; disabled: boolean
  onMuteToggle: () => void; onConnect: () => void; onDisconnect: () => void; onSend: () => void
}

export function ControlTray({ callState, muted, volume, onMuteToggle, onConnect, onDisconnect, disabled, recording, onSend }: Props) {
  const active = !['idle', 'ended'].includes(callState)
  return <div className="absolute bottom-0 inset-x-0 flex justify-center pb-7 sm:pb-9 z-20 px-4"><div className="flex items-center gap-3 rounded-3xl border border-white/10 bg-[#141719]/95 p-3 shadow-2xl backdrop-blur-xl">
    {active && <><button aria-label={muted ? 'Unmute microphone' : 'Mute microphone'} aria-pressed={muted} onClick={onMuteToggle} disabled={callState === 'connecting'} className={`h-12 w-12 grid place-items-center rounded-2xl border transition-colors ${muted ? 'bg-red-500/20 text-red-300 border-red-500/30' : 'bg-white/5 border-white/10 text-zinc-200'}`}>{muted ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}</button><div className="w-10 grid place-items-center"><AudioPulse active={callState === 'speaking' || callState === 'thinking'} volume={volume} /></div>{recording && <button onClick={onSend} className="flex items-center gap-2 px-4 h-12 rounded-2xl bg-[#a8dab5]/10 border border-[#a8dab5]/20 text-[#a8dab5] text-xs"><Send className="h-4 w-4" />Send response</button>}</>}
    <button onClick={active ? onDisconnect : onConnect} disabled={!active && disabled} className={`h-12 flex items-center justify-center gap-2.5 rounded-2xl px-5 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${active ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-[#a8dab5] hover:bg-[#c1e7cb] text-[#06230f]'}`}>{active ? <PhoneOff className="h-5 w-5" /> : <Phone className="h-5 w-5" />}{active ? 'End call' : callState === 'ended' ? 'Resume call' : 'Start consultation'}</button>
  </div></div>
}
