export const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '')

export class BackendRequestError extends Error {
  constructor(message: string, public status: number, public requiresRetry: boolean = false) {
    super(message)
    this.name = 'BackendRequestError'
  }
}

export async function readResponse<T = any>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message
    throw new BackendRequestError(detail || data.error || `Request failed (${response.status})`, response.status, Boolean(data.requires_retry || data.detail?.requires_retry))
  }
  return data
}
