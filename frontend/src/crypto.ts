import { fromBER, Sequence, OctetString, ObjectIdentifier, Integer } from 'asn1js'
import { Certificate } from 'pkijs'

// --- OID mappings ---

const PRF_OIDS: Record<string, string> = {
  '1.2.840.113549.2.7': 'SHA-1',
  '1.2.840.113549.2.9': 'SHA-256',
  '1.2.840.113549.2.10': 'SHA-384',
  '1.2.840.113549.2.11': 'SHA-512',
}

const ENC_SCHEME_OIDS: Record<string, number> = {
  '2.16.840.1.101.3.4.1.2': 16,   // aes128-CBC
  '2.16.840.1.101.3.4.1.22': 24,  // aes192-CBC
  '2.16.840.1.101.3.4.1.42': 32,  // aes256-CBC
}

const RSA_OID = '1.2.840.113549.1.1.1'
const EC_OID = '1.2.840.10045.2.1'

const EC_CURVES: Record<string, string> = {
  '1.2.840.10045.3.1.7': 'P-256',
  '1.3.132.0.34': 'P-384',
  '1.3.132.0.35': 'P-521',
}

const OID_ORG_IDENTIFIER = '2.5.4.97'
const OID_SERIAL_NUMBER = '2.5.4.5'
const OID_ORG_NAME = '2.5.4.10'
const OID_COMMON_NAME = '2.5.4.3'

// --- Binary / base64 utilities ---

export function pemToArrayBuffer(pem: string): ArrayBuffer {
  const base64 = pem
    .split('\n')
    .filter(line => !line.startsWith('-----'))
    .join('')
    .replace(/\s/g, '')
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer as ArrayBuffer
}

export function arrayBufferToBase64(data: ArrayBuffer | Uint8Array): string {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data)
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary)
}

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer as ArrayBuffer
}

// --- ASN.1 helpers ---

/** Extract algorithm OID from a PKCS#8 PrivateKeyInfo or SPKI structure. */
function detectAlgorithmOid(der: ArrayBuffer): { algoOid: string; algoParams: Sequence | null } {
  const asn1 = fromBER(der)
  if (asn1.offset === -1) throw new Error('Invalid DER format')
  const seq = asn1.result as Sequence
  const algoSeq = seq.valueBlock.value[1] as Sequence
  const algoOid = (algoSeq.valueBlock.value[0] as ObjectIdentifier).valueBlock.toString()
  const algoParams = algoSeq.valueBlock.value.length > 1 ? algoSeq.valueBlock.value[1] as Sequence : null
  return { algoOid, algoParams }
}

function detectSpkiAlgorithmOid(spkiDer: ArrayBuffer): { algoOid: string } {
  const asn1 = fromBER(spkiDer)
  if (asn1.offset === -1) throw new Error('Invalid SPKI format')
  const seq = asn1.result as Sequence
  const algoSeq = seq.valueBlock.value[0] as Sequence
  const algoOid = (algoSeq.valueBlock.value[0] as ObjectIdentifier).valueBlock.toString()
  return { algoOid }
}

function detectEcCurve(algoSeq: Sequence): string {
  const curveOid = (algoSeq.valueBlock.value[1] as ObjectIdentifier).valueBlock.toString()
  const namedCurve = EC_CURVES[curveOid]
  if (!namedCurve) throw new Error(`Nieobsługiwana krzywa EC: OID ${curveOid}`)
  return namedCurve
}

function detectSpkiEcCurve(spkiDer: ArrayBuffer): string {
  const asn1 = fromBER(spkiDer)
  const seq = asn1.result as Sequence
  const algoSeq = seq.valueBlock.value[0] as Sequence
  return detectEcCurve(algoSeq)
}

// --- PKCS#8 encrypted private key decryption ---

async function decryptPkcs8(encryptedDer: ArrayBuffer, password: string): Promise<ArrayBuffer> {
  const asn1 = fromBER(encryptedDer)
  if (asn1.offset === -1) throw new Error('Invalid encrypted key format')

  const root = asn1.result as Sequence
  const children = root.valueBlock.value

  // EncryptedPrivateKeyInfo = SEQUENCE { encryptionAlgorithm, encryptedData }
  const algoSeq = children[0] as Sequence
  const encryptedData = new Uint8Array((children[1] as OctetString).valueBlock.valueHexView)

  // Verify PBES2 (OID 1.2.840.113549.1.5.13)
  const pbes2Oid = (algoSeq.valueBlock.value[0] as ObjectIdentifier).valueBlock.toString()
  if (pbes2Oid !== '1.2.840.113549.1.5.13') {
    throw new Error(`Unsupported encryption: expected PBES2, got OID ${pbes2Oid}`)
  }

  const pbes2Params = (algoSeq.valueBlock.value[1] as Sequence).valueBlock.value

  // Parse PBKDF2 params
  const kdfSeq = pbes2Params[0] as Sequence
  const kdfOid = (kdfSeq.valueBlock.value[0] as ObjectIdentifier).valueBlock.toString()
  if (kdfOid !== '1.2.840.113549.1.5.12') {
    throw new Error(`Unsupported KDF: expected PBKDF2, got OID ${kdfOid}`)
  }

  const pbkdf2Params = (kdfSeq.valueBlock.value[1] as Sequence).valueBlock.value
  const salt = new Uint8Array((pbkdf2Params[0] as OctetString).valueBlock.valueHexView)
  const iterations = (pbkdf2Params[1] as Integer).valueBlock.valueDec

  // PRF hash — optional, defaults to SHA-1
  let hash = 'SHA-1'
  for (let i = 2; i < pbkdf2Params.length; i++) {
    if (pbkdf2Params[i] instanceof Sequence) {
      const prfOid = ((pbkdf2Params[i] as Sequence).valueBlock.value[0] as ObjectIdentifier)
        .valueBlock.toString()
      hash = PRF_OIDS[prfOid] ?? 'SHA-1'
    }
  }

  // Parse encryption scheme (AES-CBC)
  const encSchemeSeq = pbes2Params[1] as Sequence
  const encOid = (encSchemeSeq.valueBlock.value[0] as ObjectIdentifier).valueBlock.toString()
  const iv = new Uint8Array((encSchemeSeq.valueBlock.value[1] as OctetString).valueBlock.valueHexView)

  const keyLength = ENC_SCHEME_OIDS[encOid]
  if (!keyLength) throw new Error(`Unsupported encryption scheme OID: ${encOid}`)

  // Derive decryption key with PBKDF2
  const passwordKey = await window.crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveBits'],
  )
  const derivedBits = await window.crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt, iterations, hash },
    passwordKey,
    keyLength * 8,
  )
  const decryptionKey = await window.crypto.subtle.importKey(
    'raw',
    derivedBits,
    'AES-CBC',
    false,
    ['decrypt'],
  )

  return window.crypto.subtle.decrypt({ name: 'AES-CBC', iv }, decryptionKey, encryptedData)
}

// --- Private key import ---

export async function decryptPrivateKey(
  keyPem: string,
  password: string,
): Promise<{ signingKey: CryptoKey; unwrapKey: CryptoKey }> {
  const isEncrypted = keyPem.includes('ENCRYPTED')
  const der = pemToArrayBuffer(keyPem)

  let pkcs8Der: ArrayBuffer
  try {
    pkcs8Der = isEncrypted ? await decryptPkcs8(der, password) : der
  } catch (e) {
    if (isEncrypted && e instanceof DOMException) {
      throw new Error('Nieprawidłowe hasło klucza')
    }
    throw e
  }

  // Detect key algorithm from PKCS#8 PrivateKeyInfo
  const { algoOid } = detectAlgorithmOid(pkcs8Der)

  if (algoOid === RSA_OID) {
    const signingKey = await window.crypto.subtle.importKey(
      'pkcs8', pkcs8Der,
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
      false, ['sign'],
    )
    const unwrapKey = await window.crypto.subtle.importKey(
      'pkcs8', pkcs8Der,
      { name: 'RSA-OAEP', hash: 'SHA-256' },
      false, ['unwrapKey'],
    )
    return { signingKey, unwrapKey }
  }

  if (algoOid === EC_OID) {
    // Detect curve from PKCS#8 algorithm params
    const asn1 = fromBER(pkcs8Der)
    const seq = asn1.result as Sequence
    const algoSeq = seq.valueBlock.value[1] as Sequence
    const namedCurve = detectEcCurve(algoSeq)

    const signingKey = await window.crypto.subtle.importKey(
      'pkcs8', pkcs8Der,
      { name: 'ECDSA', namedCurve },
      false, ['sign'],
    )
    // For EC: use ECDH for AES key wrapping/unwrapping via key derivation
    const unwrapKey = await window.crypto.subtle.importKey(
      'pkcs8', pkcs8Der,
      { name: 'ECDH', namedCurve },
      false, ['deriveKey'],
    )
    return { signingKey, unwrapKey }
  }

  throw new Error(`Nieobsługiwany algorytm klucza: OID ${algoOid}`)
}

// --- Certificate parsing ---

export async function parseCertificate(
  certPem: string,
): Promise<{ derBytes: Uint8Array; publicKey: CryptoKey }> {
  const derBuffer = pemToArrayBuffer(certPem)
  const derBytes = new Uint8Array(derBuffer)

  const asn1 = fromBER(derBuffer)
  if (asn1.offset === -1) throw new Error('Nieprawidłowy format certyfikatu')

  const cert = new Certificate({ schema: asn1.result })
  const spkiDer = cert.subjectPublicKeyInfo.toSchema().toBER(false)

  // Detect algorithm from SPKI
  const { algoOid } = detectSpkiAlgorithmOid(spkiDer)

  let publicKey: CryptoKey
  if (algoOid === RSA_OID) {
    publicKey = await window.crypto.subtle.importKey(
      'spki', spkiDer,
      { name: 'RSA-OAEP', hash: 'SHA-256' },
      false, ['wrapKey'],
    )
  } else if (algoOid === EC_OID) {
    const namedCurve = detectSpkiEcCurve(spkiDer)
    publicKey = await window.crypto.subtle.importKey(
      'spki', spkiDer,
      { name: 'ECDH', namedCurve },
      false, [],
    )
  } else {
    throw new Error(`Nieobsługiwany algorytm w certyfikacie: OID ${algoOid}`)
  }

  return { derBytes, publicKey }
}

export function extractIdentityFromCert(certDer: Uint8Array): { nip: string | null; pesel: string | null; name: string } {
  const asn1 = fromBER(new Uint8Array(certDer))
  if (asn1.offset === -1) throw new Error('Nieprawidłowy format certyfikatu')

  const cert = new Certificate({ schema: asn1.result })

  let nip: string | null = null
  let pesel: string | null = null
  let name = 'Nieznany'

  for (const rdn of cert.subject.typesAndValues) {
    const raw = rdn.value as any
    const value = raw.valueBlock?.value ?? raw.getValue?.() ?? raw.toString?.() ?? ''

    if (rdn.type === OID_ORG_IDENTIFIER) {
      const match = String(value).match(/VATPL-(\d{10})/)
      if (match?.[1]) nip = match[1]
    }
    if (rdn.type === OID_SERIAL_NUMBER) {
      const tinMatch = String(value).match(/TINPL-(\d{10})/)
      if (tinMatch?.[1]) nip = tinMatch[1]
      const pnoMatch = String(value).match(/PNOPL-(\d{11})/)
      if (pnoMatch?.[1]) pesel = pnoMatch[1]
    }
    if (rdn.type === OID_ORG_NAME) {
      name = String(value)
    }
    if (rdn.type === OID_COMMON_NAME && name === 'Nieznany') {
      name = String(value)
    }
  }

  if (!nip && !pesel) throw new Error('Nie znaleziono NIP ani PESEL w certyfikacie')
  return { nip, pesel, name }
}

// --- AES key operations ---

export async function generateAesKey(): Promise<CryptoKey> {
  // extractable: true — needed for wrapKey and re-import as non-extractable
  return window.crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    true,
    ['encrypt', 'decrypt'],
  )
}

export async function wrapAesKey(
  aesKey: CryptoKey,
  publicKey: CryptoKey,
  ecdhPrivateKey?: CryptoKey,
): Promise<ArrayBuffer> {
  if (publicKey.algorithm.name === 'RSA-OAEP') {
    return window.crypto.subtle.wrapKey('raw', aesKey, publicKey, { name: 'RSA-OAEP' })
  }
  // EC: derive wrapping key via ECDH, then AES-KW
  if (!ecdhPrivateKey) throw new Error('ECDH private key required for EC wrapping')
  const wrappingKey = await window.crypto.subtle.deriveKey(
    { name: 'ECDH', public: publicKey },
    ecdhPrivateKey,
    { name: 'AES-KW', length: 256 },
    false,
    ['wrapKey'],
  )
  return window.crypto.subtle.wrapKey('raw', aesKey, wrappingKey, 'AES-KW')
}

export async function unwrapAesKey(
  wrapped: ArrayBuffer,
  privateKey: CryptoKey,
  ecdhPublicKey?: CryptoKey,
): Promise<CryptoKey> {
  if (privateKey.algorithm.name === 'RSA-OAEP') {
    return window.crypto.subtle.unwrapKey(
      'raw', wrapped, privateKey,
      { name: 'RSA-OAEP' },
      { name: 'AES-GCM', length: 256 },
      false, ['encrypt', 'decrypt'],
    )
  }
  // EC: derive wrapping key via ECDH, then AES-KW unwrap
  if (!ecdhPublicKey) throw new Error('ECDH public key required for EC unwrapping')
  const wrappingKey = await window.crypto.subtle.deriveKey(
    { name: 'ECDH', public: ecdhPublicKey },
    privateKey,
    { name: 'AES-KW', length: 256 },
    false,
    ['unwrapKey'],
  )
  return window.crypto.subtle.unwrapKey(
    'raw', wrapped, wrappingKey,
    'AES-KW',
    { name: 'AES-GCM', length: 256 },
    false, ['encrypt', 'decrypt'],
  )
}

/** Re-import an extractable AES key as non-extractable (for IndexedDB storage). */
export async function makeNonExtractable(aesKey: CryptoKey): Promise<CryptoKey> {
  const raw = await window.crypto.subtle.exportKey('raw', aesKey)
  return window.crypto.subtle.importKey(
    'raw',
    raw,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

// --- Request signing ---

export async function signRequest(
  privateKey: CryptoKey,
  method: string,
  path: string,
  timestamp: number,
): Promise<string> {
  const message = `${method}\n${path}\n${timestamp}`
  const data = new TextEncoder().encode(message)

  const algo: AlgorithmIdentifier = privateKey.algorithm.name === 'ECDSA'
    ? { name: 'ECDSA', hash: 'SHA-256' } as EcdsaParams
    : { name: 'RSASSA-PKCS1-v1_5' }

  const signature = await window.crypto.subtle.sign(algo, privateKey, data)
  return arrayBufferToBase64(signature)
}

// --- IndexedDB for AES key persistence ---

const IDB_NAME = 'ksefcio'
const IDB_STORE = 'aes-keys'
const IDB_VERSION = 1

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(IDB_NAME, IDB_VERSION)
    request.onupgradeneeded = () => {
      request.result.createObjectStore(IDB_STORE)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function storeAesKey(nip: string, key: CryptoKey): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite')
    tx.objectStore(IDB_STORE).put(key, nip)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}

export async function loadAesKey(nip: string): Promise<CryptoKey | null> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readonly')
    const req = tx.objectStore(IDB_STORE).get(nip)
    req.onsuccess = () => { db.close(); resolve(req.result ?? null) }
    req.onerror = () => { db.close(); reject(req.error) }
  })
}

export async function deleteAesKey(nip: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite')
    tx.objectStore(IDB_STORE).delete(nip)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}
