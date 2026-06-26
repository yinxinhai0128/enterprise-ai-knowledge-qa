import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 my-2 text-xs">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800">
        <span className="text-gray-400 font-mono">{lang || 'code'}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 text-gray-400 hover:text-white transition-colors"
        >
          {copied
            ? <><Check className="w-3 h-3" />已复制</>
            : <><Copy className="w-3 h-3" />复制</>}
        </button>
      </div>
      <pre className="bg-gray-900 px-4 py-3 overflow-x-auto scrollbar-thin">
        <code className="text-emerald-400 font-mono leading-relaxed whitespace-pre">{code}</code>
      </pre>
    </div>
  )
}

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/)
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
        }
        if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
          return (
            <code key={i} className="px-1.5 py-0.5 rounded-md bg-gray-100 text-gray-800 font-mono text-[0.85em] border border-gray-200">
              {part.slice(1, -1)}
            </code>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

function ParagraphGroup({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/)
  return (
    <>
      {paragraphs.map((para, pi) => {
        const lines = para.split('\n').filter(l => l !== '')
        if (!lines.length) return null

        // Heading #/##/###
        if (/^#{1,3}\s/.test(lines[0])) {
          return (
            <h3 key={pi} className="font-semibold text-gray-900 mt-3 mb-1 first:mt-0">
              <InlineMarkdown text={lines[0].replace(/^#{1,3}\s/, '')} />
            </h3>
          )
        }

        // Blockquote
        if (/^>\s?/.test(lines[0])) {
          return (
            <blockquote key={pi} className="border-l-2 border-gray-300 pl-3 text-gray-500 italic my-1">
              {lines.map((line, li) => (
                <p key={li}><InlineMarkdown text={line.replace(/^>\s?/, '')} /></p>
              ))}
            </blockquote>
          )
        }

        // Ordered list
        if (/^\d+\.\s/.test(lines[0])) {
          return (
            <ol key={pi} className="list-decimal list-outside ml-4 space-y-1">
              {lines.map((line, li) => (
                <li key={li} className="text-gray-800 pl-0.5">
                  <InlineMarkdown text={line.replace(/^\d+\.\s*/, '')} />
                </li>
              ))}
            </ol>
          )
        }

        // Unordered list
        if (/^[-*]\s/.test(lines[0])) {
          return (
            <ul key={pi} className="list-disc list-outside ml-4 space-y-1">
              {lines.map((line, li) => (
                <li key={li} className="text-gray-800 pl-0.5">
                  <InlineMarkdown text={line.replace(/^[-*]\s*/, '')} />
                </li>
              ))}
            </ul>
          )
        }

        // Paragraph
        return (
          <p key={pi} className="text-gray-800">
            {lines.map((line, li) => (
              <span key={li}>
                {li > 0 && <br />}
                <InlineMarkdown text={line} />
              </span>
            ))}
          </p>
        )
      })}
    </>
  )
}

/**
 * 轻量 Markdown 渲染器。支持：代码块（带复制）、行内代码、加粗、
 * #/##/### 标题、引用块、有序/无序列表、段落换行。
 */
export function SimpleMarkdown({ text }: { text: string }) {
  if (!text) return null

  // Split on fenced code blocks first — they may contain blank lines
  const segments = text.split(/(```[\w]*\n[\s\S]*?```)/g)

  return (
    <div className="space-y-2 leading-relaxed">
      {segments.map((seg, i) => {
        if (seg.startsWith('```')) {
          const firstNL = seg.indexOf('\n')
          const lang = seg.slice(3, firstNL).trim()
          const code = seg.slice(firstNL + 1).replace(/```$/, '').trimEnd()
          return <CodeBlock key={i} lang={lang} code={code} />
        }
        if (!seg.trim()) return null
        return <ParagraphGroup key={i} text={seg} />
      })}
    </div>
  )
}
