import { apiFetch } from './api'
import { useAuthStore } from './stores/auth'
import { signDigest, base64ToArrayBuffer } from './crypto'

export async function authenticateKsef(nip: string): Promise<{ accessToken: string; refreshToken: string }> {
  const auth = useAuthStore()
  if (!auth.signingKey) throw new Error('Not authenticated')

  // 1. Prepare: backend gets challenge from KSeF, builds XAdES envelope
  console.log('[ksef] Preparing auth for NIP', nip)
  const prepareRes = await apiFetch('/api/ksef/auth/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nip }),
  })
  if (!prepareRes.ok) {
    const body = await prepareRes.text()
    throw new Error(`KSeF prepare failed: HTTP ${prepareRes.status} — ${body}`)
  }

  const { request_id, signed_info_b64 } = await prepareRes.json()
  console.log('[ksef] Got SignedInfo to sign, request_id:', request_id)

  // 2. Sign the canonical SignedInfo bytes with the private key
  const signatureValue = await signDigest(auth.signingKey, base64ToArrayBuffer(signed_info_b64))
  console.log('[ksef] Signed, submitting to KSeF...')

  // 3. Finalize: backend inserts signature, submits to KSeF, redeems tokens
  const finalizeRes = await apiFetch('/api/ksef/auth/finalize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id, signature_value_b64: signatureValue }),
  })
  if (!finalizeRes.ok) {
    const body = await finalizeRes.text()
    throw new Error(`KSeF finalize failed: HTTP ${finalizeRes.status} — ${body}`)
  }

  const tokens = await finalizeRes.json()
  console.log('[ksef] Auth complete, got access token')
  return { accessToken: tokens.access_token, refreshToken: tokens.refresh_token }
}
