'use client'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Download } from 'lucide-react'

const SECTIONS = [
  ['initial_details', 'Initial Details (Incident, Timeline, Profiles)'],
  ['opposition_case', "Opposition Side’s Case"],
  ['precedents', 'Precedents'],
  ['fuzziness_and_gaps', 'Fuzziness & Missing Clarity'],
  ['law_sections', 'Relevant Law Sections'],
  ['our_arguments', 'Strong Points & Arguments (Our Side)'],
  ['win_probability', 'Win Probability Assessment'],
] as const

export function FinalPacketView({ packet, markdown }: { packet: any; markdown: string | null }) {
  const [active, setActive] = useState<string>('initial_details')
  const section = SECTIONS.find(item => item[0] === active)!
  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown || JSON.stringify(packet, null, 2)], { type: markdown ? 'text/markdown' : 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = markdown ? 'nyayalens-case-brief.md' : 'nyayalens-case-brief.json'; link.click(); URL.revokeObjectURL(url)
  }
  return <section className="h-full flex flex-col min-h-0"><header className="px-5 py-4 flex items-center justify-between border-b border-white/[.07]"><div><h2 className="text-sm font-semibold">Case intelligence packet</h2><p className="mt-1 text-[11px] text-zinc-500">Prepared for advocate review</p></div><button onClick={download} className="text-xs text-[#a8dab5] flex items-center gap-2"><Download className="h-4 w-4" />Export</button></header><nav aria-label="Packet sections" className="flex gap-1 px-3 py-3 overflow-x-auto shrink-0 border-b border-white/[.07]">{SECTIONS.map(([key, label], index) => <button key={key} onClick={() => setActive(key)} className={`text-xs whitespace-nowrap px-3 py-2 rounded-lg border ${active === key ? 'text-[#a8dab5] bg-[#a8dab5]/10 border-[#a8dab5]/20' : 'text-zinc-500 border-transparent hover:text-zinc-300'}`}><span className="mr-2 text-[10px] opacity-50">0{index + 1}</span>{label}</button>)}</nav><div className="flex-1 overflow-y-auto p-5 sm:p-8"><motion.div key={active} initial={{ opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }}><h3 className="text-xl font-medium tracking-tight mb-6">{section[1]}</h3>{packet?.[active] !== undefined ? <PacketContent value={packet[active]} /> : markdown ? <div className="whitespace-pre-wrap text-sm text-zinc-300 leading-7">{markdown}</div> : <p className="text-sm text-zinc-500">This section was not supplied by the analysis. Review the available evidence before drawing conclusions.</p>}</motion.div></div></section>
}

function PacketContent({ value, depth = 0 }: { value: any; depth?: number }) {
  if (value === null || value === undefined || value === '') return <span className="text-zinc-500 text-sm">Not established</span>
  if (typeof value === 'string') {
    if (/^https?:\/\//.test(value)) return <a href={value} target="_blank" rel="noopener noreferrer" className="text-[#a8dab5] text-sm break-all underline underline-offset-4">View source</a>
    return <p className="text-sm leading-7 text-zinc-300 whitespace-pre-wrap">{value}</p>
  }
  if (typeof value !== 'object') return <span className="text-sm text-zinc-300">{String(value)}</span>
  if (Array.isArray(value)) return value.length ? <div className="space-y-4">{value.map((item, index) => <div key={index} className="pl-4 border-l border-[#a8dab5]/20"><PacketContent value={item} depth={depth + 1} /></div>)}</div> : <p className="text-sm text-zinc-500">No items identified in the available evidence.</p>
  return <dl className={`space-y-5 ${depth === 0 ? '' : 'rounded-xl bg-white/[.02] border border-white/[.05] p-4'}`}>{Object.entries(value).map(([key, item]) => <div key={key}><dt className="text-[10px] uppercase tracking-[.12em] text-zinc-500 mb-2">{key.replace(/_/g, ' ')}</dt><dd><PacketContent value={item} depth={depth + 1} /></dd></div>)}</dl>
}
