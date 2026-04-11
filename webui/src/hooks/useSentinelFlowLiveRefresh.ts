import { useEffect } from 'react'

type LiveRefreshOptions = {
  enabled?: boolean
  intervalMs?: number
}

export function useSentinelFlowLiveRefresh(
  callback: () => void | Promise<void>,
  options: LiveRefreshOptions = {},
) {
  const { enabled = true, intervalMs = 5000 } = options

  useEffect(() => {
    if (!enabled) return

    const run = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return
      }
      void callback()
    }

    const timer = window.setInterval(run, intervalMs)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        run()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [callback, enabled, intervalMs])
}
