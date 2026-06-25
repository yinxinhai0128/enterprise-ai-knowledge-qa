// 极简 Markdown 渲染：仅处理 **加粗** 与换行（保留 pre-wrap）。
// 后端答案偶含 **重点** 标记，无需引入完整 markdown 库。
export function SimpleMarkdown({ text }: { text: string }) {
  return (
    <span style={{ whiteSpace: 'pre-wrap' }}>
      {text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={i}>{part.slice(2, -2)}</strong>
          : part
      )}
    </span>
  )
}
