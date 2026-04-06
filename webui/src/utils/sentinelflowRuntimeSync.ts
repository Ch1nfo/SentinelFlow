export type RuntimeActivity = {
  type: 'alert_action' | 'command_dispatch'
  title: string
  detail: string
  success: boolean
  timestamp: string
}

const STORAGE_KEY = 'sentinelflow:last-runtime-activity'
const EVENT_NAME = 'sentinelflow:runtime-activity'

export function publishRuntimeActivity(activity: RuntimeActivity) {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(activity))
  window.dispatchEvent(new CustomEvent<RuntimeActivity>(EVENT_NAME, { detail: activity }))
}

export function readRuntimeActivity(): RuntimeActivity | null {
  if (typeof window === 'undefined') return null
  const value = window.sessionStorage.getItem(STORAGE_KEY)
  if (!value) return null
  try {
    return JSON.parse(value) as RuntimeActivity
  } catch {
    return null
  }
}

export function subscribeRuntimeActivity(handler: (activity: RuntimeActivity) => void) {
  if (typeof window === 'undefined') return () => undefined
  const listener = (event: Event) => {
    const customEvent = event as CustomEvent<RuntimeActivity>
    if (customEvent.detail) {
      handler(customEvent.detail)
    }
  }
  window.addEventListener(EVENT_NAME, listener)
  return () => window.removeEventListener(EVENT_NAME, listener)
}
