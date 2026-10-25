import { NextRequest } from 'next/server'
import { verifyToken } from './auth'

export function getAuthPayload(req: NextRequest) {
  const token = req.cookies.get('nyaya_token')?.value || req.headers.get('authorization')?.replace('Bearer ', '')
  if (!token) return null
  return verifyToken(token)
}

export function backendAuthHeaders(req: NextRequest): Record<string, string> {
  const authorization = req.headers.get('authorization')
  const cookie = req.headers.get('cookie')
  return { ...(authorization ? { Authorization: authorization } : {}), ...(cookie ? { Cookie: cookie } : {}) }
}
