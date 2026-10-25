import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ token: string }> }
) {
  const params = await context.params
  try {
    const session = await prisma.caseSession.findUnique({
      where: { shareLink: params.token }
    })

    if (!session) {
      return NextResponse.json({ error: 'Session not found' }, { status: 404 })
    }
    if (session.callStatus === 'IN_PROGRESS') return NextResponse.json({ success: true })

    await prisma.caseSession.update({
      where: { id: session.id },
      data: {
        callStatus: 'IN_PROGRESS',
        callAttempts: { increment: 1 },
        lastCallAt: new Date()
      }
    })

    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('Failed to update call start:', error)
    return NextResponse.json(
      { error: 'Unable to begin consultation' },
      { status: 500 }
    )
  }
}
