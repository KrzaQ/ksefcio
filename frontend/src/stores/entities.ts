import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface Entity {
  identity: string  // NIP or PESEL (user identifier from cert)
  name: string
  certPem: string   // PEM certificate
  keyPem: string    // Encrypted PKCS#8 PEM (password-protected)
  ksefNips?: string[]  // Verified KSeF NIPs (persisted across sessions)
  nipSettings?: Record<string, { bankAccount?: string }>
}

const STORAGE_KEY = 'ksefcio-entities'
const ACTIVE_KEY = 'ksefcio-active-entity'
const TEMPLATE_KEY = 'ksefcio-transfer-title-template'
export const DEFAULT_TRANSFER_TITLE_TEMPLATE = 'FV {their_id} KSeF {ksef_id}'

function loadEntities(): Entity[] {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : []
}

function loadActiveNip(): string | null {
  return localStorage.getItem(ACTIVE_KEY)
}

export const useEntitiesStore = defineStore('entities', () => {
  const entities = ref<Entity[]>(loadEntities())
  const activeIdentity = ref<string | null>(loadActiveNip())
  const transferTitleTemplate = ref<string>(
    localStorage.getItem(TEMPLATE_KEY) ?? DEFAULT_TRANSFER_TITLE_TEMPLATE
  )

  watch(entities, (val) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
  }, { deep: true })

  watch(activeIdentity, (val) => {
    if (val) {
      localStorage.setItem(ACTIVE_KEY, val)
    } else {
      localStorage.removeItem(ACTIVE_KEY)
    }
  })

  watch(transferTitleTemplate, (val) => {
    localStorage.setItem(TEMPLATE_KEY, val)
  })

  function addEntity(entity: Entity) {
    const idx = entities.value.findIndex(e => e.identity === entity.identity)
    if (idx >= 0) {
      entities.value[idx] = entity
    } else {
      entities.value.push(entity)
    }
    activeIdentity.value = entity.identity
  }

  function removeEntity(identity: string) {
    entities.value = entities.value.filter(e => e.identity !== identity)
    if (activeIdentity.value === identity) {
      activeIdentity.value = entities.value[0]?.identity ?? null
    }
  }

  function getActive(): Entity | undefined {
    return entities.value.find(e => e.identity === activeIdentity.value)
  }

  function getNipBankAccount(nip: string): string | undefined {
    return getActive()?.nipSettings?.[nip]?.bankAccount
  }

  function setNipBankAccount(nip: string, account: string) {
    const entity = getActive()
    if (!entity) return
    if (!entity.nipSettings) entity.nipSettings = {}
    if (!entity.nipSettings[nip]) entity.nipSettings[nip] = {}
    entity.nipSettings[nip].bankAccount = account
  }

  return {
    entities, activeIdentity, transferTitleTemplate,
    addEntity, removeEntity, getActive,
    getNipBankAccount, setNipBankAccount,
  }
})
