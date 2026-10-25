import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { hashPassword, signToken } from '@/lib/auth'

export async function POST(req: NextRequest) {
  try {
    const { firstName, lastName, email: rawEmail, password, phone, barCouncilId } = await req.json()
    const email = typeof rawEmail === 'string' ? rawEmail.trim().toLowerCase() : ''

    if (!firstName || !lastName || !email || !password) {
      return NextResponse.json({ error: 'All fields required' }, { status: 400 })
    }
    if (typeof firstName !== 'string' || typeof lastName !== 'string' || typeof password !== 'string' || firstName.length > 100 || lastName.length > 100 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || password.length < 8 || password.length > 200) {
      return NextResponse.json({ error: 'Enter a valid name, email, and a password of at least 8 characters' }, { status: 400 })
    }

    const existing = await prisma.lawyer.findUnique({ where: { email } })
    if (existing) {
      return NextResponse.json({ error: 'Email already registered' }, { status: 409 })
    }

    const hashedPassword = await hashPassword(password)
    const lawyer = await prisma.lawyer.create({
      data: { firstName, lastName, email, password: hashedPassword, phone, barCouncilId },
      select: { id: true, firstName: true, lastName: true, email: true, phone: true, barCouncilId: true, createdAt: true }
    })

    const token = signToken({ lawyerId: lawyer.id, email: lawyer.email })

    const response = NextResponse.json({ lawyer }, { status: 201 })
    response.cookies.set('nyaya_token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 7 * 24 * 60 * 60,
      path: '/'
    })
    return response
  } catch (err: any) {
    console.error('[register]', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
