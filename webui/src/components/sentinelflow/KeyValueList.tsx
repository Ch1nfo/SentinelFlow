type KeyValueListProps = {
  items: Array<{ label: string; value: string }>
}

export default function KeyValueList({ items }: KeyValueListProps) {
  return (
    <div className="sentinelflow-key-value-list">
      {items.map((item) => (
        <div key={`${item.label}-${item.value}`} className="sentinelflow-key-value-item">
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}
