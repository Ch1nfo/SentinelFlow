type MarkdownContentProps = {
  content: string
  inverted?: boolean
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function applyInlineMarkdown(text: string): string {
  let output = escapeHtml(text)
  output = output.replace(/`([^`]+)`/g, '<code>$1</code>')
  output = output.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  output = output.replace(/(^|[^\*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>')
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  return output
}

function renderMarkdownToHtml(markdown: string): string {
  const normalized = markdown.replace(/\r\n/g, '\n').trim()
  if (!normalized) return ''

  const lines = normalized.split('\n')
  const html: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    const codeFence = line.match(/^```([\w-]+)?\s*$/)
    if (codeFence) {
      const language = codeFence[1] ? ` class="language-${escapeHtml(codeFence[1])}"` : ''
      index += 1
      const block: string[] = []
      while (index < lines.length && !lines[index].startsWith('```')) {
        block.push(lines[index])
        index += 1
      }
      if (index < lines.length) {
        index += 1
      }
      html.push(`<pre><code${language}>${escapeHtml(block.join('\n'))}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      const level = heading[1].length
      html.push(`<h${level}>${applyInlineMarkdown(heading[2].trim())}</h${level}>`)
      index += 1
      continue
    }

    const blockquote = line.match(/^>\s?(.*)$/)
    if (blockquote) {
      const block: string[] = [blockquote[1]]
      index += 1
      while (index < lines.length) {
        const next = lines[index].match(/^>\s?(.*)$/)
        if (!next) break
        block.push(next[1])
        index += 1
      }
      html.push(`<blockquote>${block.map((item) => `<p>${applyInlineMarkdown(item)}</p>`).join('')}</blockquote>`)
      continue
    }

    const unordered = line.match(/^[-*]\s+(.+)$/)
    if (unordered) {
      const items: string[] = []
      while (index < lines.length) {
        const match = lines[index].match(/^[-*]\s+(.+)$/)
        if (!match) break
        items.push(`<li>${applyInlineMarkdown(match[1])}</li>`)
        index += 1
      }
      html.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    const ordered = line.match(/^\d+\.\s+(.+)$/)
    if (ordered) {
      const items: string[] = []
      while (index < lines.length) {
        const match = lines[index].match(/^\d+\.\s+(.+)$/)
        if (!match) break
        items.push(`<li>${applyInlineMarkdown(match[1])}</li>`)
        index += 1
      }
      html.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    const paragraph: string[] = [line]
    index += 1
    while (index < lines.length) {
      const next = lines[index]
      if (
        !next.trim() ||
        /^```/.test(next) ||
        /^(#{1,4})\s+/.test(next) ||
        /^>\s?/.test(next) ||
        /^[-*]\s+/.test(next) ||
        /^\d+\.\s+/.test(next)
      ) {
        break
      }
      paragraph.push(next)
      index += 1
    }
    html.push(`<p>${applyInlineMarkdown(paragraph.join(' '))}</p>`)
  }

  return html.join('')
}

export default function MarkdownContent({ content, inverted = false }: MarkdownContentProps) {
  const html = renderMarkdownToHtml(content)
  return (
    <div
      className={inverted ? 'prose prose-invert max-w-none' : 'prose max-w-none'}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
