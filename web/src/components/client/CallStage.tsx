'use client'
import { Scale, Check, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'
import type { CallState } from '@/hooks/useSarvamCall'
import { AudioPulse } from './ControlTray'

export function CallStage({ callState, volume, speakingText }: { callState: CallState; volume: number; speakingText: string }) {
  const active = !['idle', 'ended'].includes(callState)
  const label = { idle: 'A clearer account. A stronger beginning.', connecting: 'Connecting your consultation', connected: 'Listening to you', thinking: 'Considering your response', speaking: 'Nyaya is speaking', ended: 'Your progress is saved' }[callState]
  return <section className="flex-1 flex flex-col items-center justify-center px-6 pb-36" style={{ background: 'radial-gradient(ellipse at 50% 35%, #13221e 0%, #0b0d0e 65%)' }}>
    <div className="relative grid place-items-center"><motion.div className="absolute w-64 h-64 rounded-full bg-[#a8dab5]/5 blur-3xl" animate={{ scale: active ? [1, 1.2, 1] : 1 }} transition={{ duration: 4, repeat: Infinity }} /><motion.div className="w-32 h-32 sm:w-40 sm:h-40 relative rounded-full border border-[#a8dab5]/25 bg-gradient-to-br from-[#a8dab5]/15 to-[#0b0d0e] shadow-[inset_0_0_40px_rgba(168,218,181,0.05)] flex items-center justify-center" animate={{ scale: 1 + volume * .1 }} transition={{ duration: .1 }}>{callState === 'connecting' || callState === 'thinking' ? <Loader2 className="w-9 h-9 text-[#a8dab5] animate-spin" /> : callState === 'ended' ? <Check className="w-10 h-10 text-[#a8dab5]" /> : active ? <AudioPulse active={callState === 'speaking'} volume={volume} /> : <Scale className="w-10 h-10 text-[#a8dab5]" />}</motion.div></div>
    <h1 className="mt-8 text-center text-xl sm:text-2xl font-medium tracking-tight">{callState === 'idle' ? 'Meet Nyaya, your intake assistant' : label}</h1>
    <p className="mt-3 text-center text-sm text-zinc-500 max-w-sm leading-relaxed">{callState === 'idle' ? label : callState === 'ended' ? 'You can resume this conversation from the same link.' : 'Take your time. It is okay to say you do not remember.'}</p>
    {speakingText && active && <div aria-live="polite" className="mt-7 max-w-lg max-h-32 overflow-y-auto text-center text-sm leading-relaxed text-zinc-300 px-4">{speakingText}</div>}
  </section>
}
