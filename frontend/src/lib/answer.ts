// 答案文本处理工具。

// 后端会在答案正文末尾追加"参考来源："文字块（供 API/审计消费）。
// 前端有独立的来源卡片，故在有结构化来源时剥离正文里的重复块。
export function stripCitationBlock(answer: string): string {
  const idx = answer.indexOf('\n\n参考来源：')
  return idx >= 0 ? answer.slice(0, idx).trimEnd() : answer
}
