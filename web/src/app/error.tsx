'use client'
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return <main className="min-h-screen bg-[#0b0d0e] text-zinc-100 grid place-items-center p-8"><div className="max-w-md text-center"><h1 className="text-xl font-semibold">This view could not be loaded</h1><p className="text-sm text-zinc-400 mt-3">Your saved case information remains available. Try loading the view again.</p><button onClick={reset} className="mt-6 bg-[#a8dab5] text-[#06230f] rounded-xl px-6 py-3 text-sm">Try again</button></div></main>
}
