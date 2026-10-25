'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { BACKEND_URL, BackendRequestError, readResponse } from '@/lib/backend'

export type CallState = 'idle' | 'connecting' | 'connected' | 'thinking' | 'speaking' | 'ended'
export interface PendingDocument { docId: string; docType: string }
interface VoiceReply {
  spoken_response: string
  transcript?: string
  audio_base64?: string
  audio_mime?: string
  pending_documents?: { doc_id: string; doc_type: string }[]
  complete?: boolean
  audio_error?: string
}

export function useSarvamCall(sessionId?: string, language = 'hi') {
  const [callState, setCallState] = useState<CallState>('idle')
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(0)
  const [speakingText, setSpeakingText] = useState('')
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState('')
  const [pendingDocs, setPendingDocs] = useState<PendingDocument[]>([])
  const [recording, setRecording] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [needsRetry, setNeedsRetry] = useState(false)
  const retryPending = useRef(false)
  const phase = useRef<CallState>('idle')
  const paused = useRef(false)
  const generation = useRef(0)
  const playbackFinished = useRef<() => void>()
  const active = useRef(false)
  const mutedRef = useRef(false)
  const stream = useRef<MediaStream>()
  const context = useRef<AudioContext>()
  const analyser = useRef<AnalyserNode>()
  const recorder = useRef<MediaRecorder>()
  const audio = useRef<HTMLAudioElement>()
  const controller = useRef<AbortController>()
  const frame = useRef(0)
  const capture = useRef<() => void>(() => {})
  const submit = useRef<(blob: Blob) => Promise<void>>(async () => {})
  const transition = useCallback((next: CallState) => { phase.current = next; setCallState(next) }, [])
  const markRetry = useCallback((value: boolean) => { retryPending.current = value; setNeedsRetry(value) }, [])

  const stopRecording = useCallback((discard = false) => {
    cancelAnimationFrame(frame.current)
    if (recorder.current?.state === 'recording') {
      if (discard) recorder.current.onstop = null
      recorder.current.stop()
    }
    setRecording(false)
    setVolume(0)
  }, [])

  const end = useCallback((finished = false) => {
    generation.current += 1
    active.current = false
    controller.current?.abort()
    stopRecording(true)
    audio.current?.pause()
    playbackFinished.current?.()
    stream.current?.getTracks().forEach(track => track.stop())
    stream.current = undefined
    void context.current?.close()
    context.current = undefined
    setCompleted(finished)
    transition('ended')
  }, [stopRecording, transition])

  useEffect(() => () => {
    active.current = false
    controller.current?.abort()
    cancelAnimationFrame(frame.current)
    if (recorder.current?.state === 'recording') {
      recorder.current.onstop = null
      recorder.current.stop()
    }
    audio.current?.pause()
    playbackFinished.current?.()
    stream.current?.getTracks().forEach(track => track.stop())
    void context.current?.close()
  }, [])

  const handleReply = useCallback(async (reply: VoiceReply) => {
    if (!active.current) return
    const replyGeneration = generation.current
    setSpeakingText(reply.spoken_response || '')
    if (reply.transcript) setTranscript(reply.transcript)
    if (reply.pending_documents) setPendingDocs(reply.pending_documents.map(doc => ({ docId: doc.doc_id, docType: doc.doc_type })))
    if (reply.audio_error) setError('The voice could not be played. Please read the question below and respond when ready.')
    if (reply.audio_base64) {
      transition('speaking')
      const player = audio.current || new Audio()
      audio.current = player
      player.src = `data:${reply.audio_mime || 'audio/mpeg'};base64,${reply.audio_base64}`
      await new Promise<void>((resolve, reject) => {
        playbackFinished.current = resolve
        player.onended = () => { playbackFinished.current = undefined; resolve() }
        player.onerror = () => reject(new Error('Audio playback failed. The question is shown on screen.'))
        player.play().catch(reject)
      }).catch(cause => setError(cause instanceof Error ? cause.message : 'Tap the microphone to continue.'))
    }
    if (!active.current || generation.current !== replyGeneration) return
    if (reply.complete) { end(true); return }
    transition('connected')
    capture.current()
  }, [end, transition])

  submit.current = async (blob: Blob) => {
    if (!active.current || !sessionId) return
    const turnGeneration = generation.current
    transition('thinking')
    setError('')
    try {
      const form = new FormData()
      form.append('audio', blob, blob.type.includes('mp4') ? 'response.mp4' : 'response.webm')
      form.append('language', language)
      controller.current = new AbortController()
      const reply = await readResponse<VoiceReply>(await fetch(`${BACKEND_URL}/api/voice/${sessionId}/turn`, { method: 'POST', body: form, signal: controller.current.signal }))
      if (active.current && turnGeneration === generation.current) await handleReply(reply)
    } catch (cause) {
      if (!active.current || turnGeneration !== generation.current) return
      setError(cause instanceof Error ? cause.message : 'Could not process your response. Please try again.')
      transition('connected')
      if (cause instanceof BackendRequestError && cause.requiresRetry) markRetry(true)
      else capture.current()
    }
  }

  capture.current = () => {
    if (!active.current || phase.current !== 'connected' || retryPending.current || mutedRef.current || paused.current || !stream.current || recorder.current?.state === 'recording') return
    const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type))
    const current = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined)
    recorder.current = current
    const chunks: BlobPart[] = []
    current.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
    current.onstop = () => {
      cancelAnimationFrame(frame.current)
      setRecording(false)
      setVolume(0)
      if (active.current && chunks.length) void submit.current(new Blob(chunks, { type: current.mimeType }))
    }
    current.start()
    setRecording(true)
    let heardSpeech = false
    let lastVoice = performance.now()
    const started = lastVoice
    const samples = new Uint8Array(analyser.current!.fftSize)
    const monitor = () => {
      if (current.state !== 'recording') return
      analyser.current!.getByteTimeDomainData(samples)
      const rms = Math.sqrt(samples.reduce((total, value) => total + ((value - 128) / 128) ** 2, 0) / samples.length)
      setVolume(Math.min(1, rms * 6))
      const now = performance.now()
      if (rms > 0.025) { heardSpeech = true; lastVoice = now }
      if ((heardSpeech && now - lastVoice > 1400 && now - started > 1200) || now - started > 27000) {
        if (heardSpeech) stopRecording()
        else {
          current.onstop = () => { setRecording(false); capture.current() }
          current.stop()
        }
        return
      }
      frame.current = requestAnimationFrame(monitor)
    }
    frame.current = requestAnimationFrame(monitor)
  }

  const start = useCallback(async () => {
    if (!sessionId || active.current || phase.current === 'connecting') return
    generation.current += 1
    const startGeneration = generation.current
    setError('')
    setCompleted(false)
    markRetry(false)
    transition('connecting')
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Voice calls require a supported browser on HTTPS. Try Chrome or Safari.')
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      if (startGeneration !== generation.current) { stream.current.getTracks().forEach(track => track.stop()); return false }
      context.current = new AudioContext()
      await context.current.resume()
      analyser.current = context.current.createAnalyser()
      analyser.current.fftSize = 1024
      context.current.createMediaStreamSource(stream.current).connect(analyser.current)
      active.current = true
      mutedRef.current = false
      setMuted(false)
      controller.current = new AbortController()
      const reply = await readResponse<VoiceReply>(await fetch(`${BACKEND_URL}/api/voice/${sessionId}/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language }), signal: controller.current.signal,
      }))
      if (startGeneration !== generation.current) return false
      await handleReply(reply)
      return true
    } catch (cause) {
      if (startGeneration !== generation.current) return false
      end()
      transition('idle')
      setError(cause instanceof Error ? cause.message : 'Could not connect. Please try again.')
      return false
    }
  }, [sessionId, language, handleReply, end, transition, markRetry])

  const retryResponse = useCallback(async () => {
    if (!sessionId || !active.current || !retryPending.current || phase.current === 'thinking') return
    const retryGeneration = generation.current
    transition('thinking')
    setError('')
    try {
      controller.current = new AbortController()
      const reply = await readResponse<VoiceReply>(await fetch(`${BACKEND_URL}/api/voice/${sessionId}/retry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language }), signal: controller.current.signal,
      }))
      if (!active.current || generation.current !== retryGeneration) return
      markRetry(false)
      await handleReply(reply)
    } catch (cause) {
      if (!active.current || generation.current !== retryGeneration) return
      setError(cause instanceof Error ? cause.message : 'The saved response could not be processed. Please retry.')
      transition('connected')
      if (cause instanceof BackendRequestError && cause.status === 409) { markRetry(false); capture.current() }
    }
  }, [sessionId, language, transition, markRetry, handleReply])

  const toggleMute = useCallback(() => {
    mutedRef.current = !mutedRef.current
    setMuted(mutedRef.current)
    stream.current?.getAudioTracks().forEach(track => { track.enabled = !mutedRef.current })
    if (mutedRef.current) stopRecording(true)
    else if (phase.current === 'connected') capture.current()
  }, [stopRecording])

  const pauseForDocument = useCallback((value: boolean) => {
    paused.current = value
    if (value) stopRecording(true)
    else capture.current()
  }, [stopRecording])

  return { callState, completed, needsRetry, retryResponse, muted, volume, speakingText, transcript, error, pendingDocs, recording, start, end, toggleMute, pauseForDocument,
    sendResponse: () => stopRecording(), removeDocument: (id: string) => setPendingDocs(docs => docs.filter(doc => doc.docId !== id)) }
}
