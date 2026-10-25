import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { verifyToken } from '@/lib/auth'
import { backendAuthHeaders } from '@/lib/requireAuth'

export async function POST(req: NextRequest, context: { params: Promise<{ token: string }> }) {
  const params = await context.params
  const authToken = req.cookies.get('nyaya_token')?.value || req.headers.get('authorization')?.replace('Bearer ', '')
  const payload = verifyToken(authToken || '')
  if (!payload) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const session = await prisma.caseSession.findUnique({ where: { shareLink: params.token } })
  if (!session || session.lawyerId !== payload.lawyerId) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000'
  
  // Trigger deep analysis on FastAPI backend
  const res = await fetch(`${backendUrl || 'http://localhost:8000'}/api/session/${session.backendSessionId}/accept-case`, {
    method: 'POST', headers: backendAuthHeaders(req)
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) return NextResponse.json({ error: data.detail || 'Analysis could not be started' }, { status: res.status })

  // Update status in Prisma
  await prisma.caseSession.update({
    where: { id: session.id },
    data: { status: 'ANALYSIS' }
  })

  return NextResponse.json({ status: 'analysis_started', backendResponse: data })
}
