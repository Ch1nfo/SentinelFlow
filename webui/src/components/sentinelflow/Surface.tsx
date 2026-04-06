import type { PropsWithChildren } from 'react'

type SurfaceProps = PropsWithChildren<{
  title: string
  subtitle?: string
}>

export default function Surface({ title, subtitle, children }: SurfaceProps) {
  return (
    <section className="sentinelflow-surface">
      {title || subtitle ? (
        <div className="sentinelflow-surface-header">
          {title ? <h2>{title}</h2> : null}
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      ) : null}
      <div className="sentinelflow-surface-body">{children}</div>
    </section>
  )
}
