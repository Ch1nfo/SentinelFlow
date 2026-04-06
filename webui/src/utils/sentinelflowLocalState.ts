export function readSessionValue<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback
  const raw = window.sessionStorage.getItem(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function writeSessionValue<T>(key: string, value: T) {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(key, JSON.stringify(value))
}

export function readLocalValue<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback
  const raw = window.localStorage.getItem(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function writeLocalValue<T>(key: string, value: T) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, JSON.stringify(value))
}

export function removeLocalValue(key: string) {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(key)
}
