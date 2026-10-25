import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { getAuthPayload, backendAuthHeaders } from '@/lib/requireAuth'

export async function POST(req: NextRequest, context: { params: Promise<{ token: string }> }) {
  const params = await context.params
  const owner = getAuthPayload(req)
  if (!owner) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  const session = await prisma.caseSession.findUnique({ where: { shareLink: params.token } })
  if (!session || session.lawyerId !== owner.lawyerId) return NextResponse.json({ error: 'Session not found' }, { status: 404 })
  const backend = process.env.BACKEND_URL || 'http://localhost:8000'
  const packet = await fetch(`${backend}/api/session/${session.backendSessionId}/packet`, { headers: backendAuthHeaders(req), cache: 'no-store', signal: AbortSignal.timeout(10000) })
  if (!packet.ok) return NextResponse.json({ error: 'The analysis packet is not ready' }, { status: 409 })
  await prisma.caseSession.update({
    where: { shareLink: params.token },
    data: { status: 'DONE' }
  })
  return NextResponse.json({ success: true })
}
