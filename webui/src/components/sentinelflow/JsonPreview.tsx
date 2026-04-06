type JsonPreviewProps = {
  value: unknown
}

export default function JsonPreview({ value }: JsonPreviewProps) {
  return <pre className="sentinelflow-code-block">{JSON.stringify(value, null, 2)}</pre>
}
