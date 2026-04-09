import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface Entity {
  nip: string       // NIP or PESEL (user identifier from cert)
  name: string
  certPem: string   // PEM certificate
  keyPem: string    // Encrypted PKCS#8 PEM (password-protected)
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
  const activeNip = ref<string | null>(loadActiveNip())

  watch(entities, (val) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
  }, { deep: true })

  watch(activeNip, (val) => {
    if (val) {
      localStorage.setItem(ACTIVE_KEY, val)
    } else {
      localStorage.removeItem(ACTIVE_KEY)
    }
  })

  function addEntity(entity: Entity) {
    const idx = entities.value.findIndex(e => e.nip === entity.nip)
    if (idx >= 0) {
      entities.value[idx] = entity
    } else {
      entities.value.push(entity)
    }
    activeNip.value = entity.nip
  }

  function removeEntity(nip: string) {
    entities.value = entities.value.filter(e => e.nip !== nip)
    if (activeNip.value === nip) {
      activeNip.value = entities.value[0]?.nip ?? null
    }
  }

  function getActive(): Entity | undefined {
    return entities.value.find(e => e.nip === activeNip.value)
  }

  return { entities, activeNip, addEntity, removeEntity, getActive }
})
