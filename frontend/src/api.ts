import { useAuthStore } from './stores/auth'
import { arrayBufferToBase64, signRequest } from './crypto'

/**
 * Signed fetch wrapper. Every request gets X-Cert, X-Timestamp, X-Signature headers
 * using the active session's signing key and certificate.
 */
export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const auth = useAuthStore()
  if (!auth.signingKey || !auth.certDer) {
    throw new Error('Not authenticated')
  }

  const timestamp = Math.floor(Date.now() / 1000)
  const signature = await signRequest(auth.signingKey, (options.method ?? 'GET').toUpperCase(), path, timestamp)

  const headers = new Headers(options.headers)
  headers.set('X-Cert', arrayBufferToBase64(auth.certDer))
  headers.set('X-Timestamp', String(timestamp))
  headers.set('X-Signature', signature)

  return fetch(path, { ...options, headers })
}
