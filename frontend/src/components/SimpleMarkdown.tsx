/**
 * 轻量 Markdown 渲染器，不引入 react-markdown / remark 等重依赖。
 * 支持：**加粗**、# 标题（h1-h3 → 同一 h3 样式）、有序/无序列表、段落换行。
 */

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
          : <span key={i}>{part}</span>
      )}
    </>
  )
}

export function SimpleMarkdown({ text }: { text: string }) {
  if (!text) return null

  const paragraphs = text.split(/\n{2,}/)

  return (
    <div className="space-y-2 leading-relaxed">
      {paragraphs.map((para, pi) => {
        const lines = para.split('\n').filter(l => l !== '')
        if (!lines.length) return null

        // 标题 #/##/###
        if (/^#{1,3}\s/.test(lines[0])) {
          return (
            <h3 key={pi} className="font-semibold text-gray-900 mt-1">
              <InlineMarkdown text={lines[0].replace(/^#{1,3}\s/, '')} />
            </h3>
          )
        }

        // 有序列表（"数字. " 开头）
        if (/^\d+\.\s/.test(lines[0])) {
          return (
            <ol key={pi} className="list-decimal list-outside ml-4 space-y-1">
              {lines.map((line, li) => (
                <li key={li} className="text-gray-800">
                  <InlineMarkdown text={line.replace(/^\d+\.\s*/, '')} />
                </li>
              ))}
            </ol>
          )
        }

        // 无序列表（- 或 * 开头）
        if (/^[-*]\s/.test(lines[0])) {
          return (
            <ul key={pi} className="list-disc list-outside ml-4 space-y-1">
              {lines.map((line, li) => (
                <li key={li} className="text-gray-800">
                  <InlineMarkdown text={line.replace(/^[-*]\s*/, '')} />
                </li>
              ))}
            </ul>
          )
        }

        // 普通段落
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
    </div>
  )
}
