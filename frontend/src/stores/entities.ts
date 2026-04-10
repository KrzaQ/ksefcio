import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface Entity {
  identity: string  // NIP or PESEL (user identifier from cert)
  name: string
  certPem: string   // PEM certificate
  keyPem: string    // Encrypted PKCS#8 PEM (password-protected)
  ksefNips?: string[]  // Verified KSeF NIPs (persisted across sessions)
}

const STORAGE_KEY = 'ksefcio-entities'
const ACTIVE_KEY = 'ksefcio-active-entity'

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

  return { entities, activeIdentity, addEntity, removeEntity, getActive }
})
