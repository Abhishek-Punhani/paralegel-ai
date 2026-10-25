import bcrypt from 'bcryptjs'
import jwt from 'jsonwebtoken'

function jwtSecret(): string {
  const secret = process.env.JWT_SECRET
  if (secret) return secret
  if (process.env.NODE_ENV === 'production') throw new Error('JWT_SECRET must be configured in production')
  return 'nyayalens-local-development-only'
}
const JWT_EXPIRES_IN = '7d'

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 12)
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash)
}

export function signToken(payload: { lawyerId: string; email: string }): string {
  return jwt.sign(payload, jwtSecret(), { expiresIn: JWT_EXPIRES_IN, algorithm: 'HS256' })
}

export function verifyToken(token: string): { lawyerId: string; email: string } | null {
  try {
    const payload = jwt.verify(token, jwtSecret(), { algorithms: ['HS256'] })
    if (typeof payload === 'string' || typeof payload.lawyerId !== 'string' || typeof payload.email !== 'string') return null
    return { lawyerId: payload.lawyerId, email: payload.email }
  } catch {
    return null
  }
}
