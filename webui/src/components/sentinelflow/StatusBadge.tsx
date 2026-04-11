type StatusBadgeProps = {
  tone?: 'neutral' | 'success' | 'warn' | 'danger' | 'info'
  children: string
}

export default function StatusBadge({ tone = 'neutral', children }: StatusBadgeProps) {
  return <span className={`sentinelflow-status-badge sentinelflow-status-badge-${tone}`}>{children}</span>
}
