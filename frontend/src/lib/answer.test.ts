import { describe, it, expect } from 'vitest'
import { stripCitationBlock } from './answer'

describe('stripCitationBlock', () => {
  it('剥离正文末尾的「参考来源」块', () => {
    const answer = '测试申请应至少提前 3 个工作日提交。\n\n参考来源：\n- [来源:stage12.txt]'
    expect(stripCitationBlock(answer)).toBe('测试申请应至少提前 3 个工作日提交。')
  })

  it('无来源块时原样返回', () => {
    const answer = '知识库中没有找到相关资料，无法基于可信证据回答。'
    expect(stripCitationBlock(answer)).toBe(answer)
  })

  it('剥离后去除尾随空白', () => {
    const answer = '答案正文。  \n\n参考来源：\n- [来源:a.txt]'
    expect(stripCitationBlock(answer)).toBe('答案正文。')
  })

  it('多条来源也整体剥离', () => {
    const answer = '正文\n\n参考来源：\n- [来源:a.txt]\n- [来源:b.txt]'
    expect(stripCitationBlock(answer)).toBe('正文')
  })

  it('只匹配带前导双换行的真实块，不误伤正文中出现的「参考来源」字样', () => {
    const answer = '我们的参考来源是内部文档，详见下文。'
    expect(stripCitationBlock(answer)).toBe(answer)
  })

  it('空字符串安全', () => {
    expect(stripCitationBlock('')).toBe('')
  })
})
