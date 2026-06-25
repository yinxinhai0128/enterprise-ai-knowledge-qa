import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SimpleMarkdown } from './SimpleMarkdown'

describe('SimpleMarkdown', () => {
  it('把 **xxx** 渲染成 <strong>', () => {
    render(<SimpleMarkdown text="测试申请应至少提前 **3 个工作日** 提交。" />)
    const strong = screen.getByText('3 个工作日')
    expect(strong.tagName).toBe('STRONG')
  })

  it('纯文本无加粗时不产生 strong', () => {
    const { container } = render(<SimpleMarkdown text="没有任何加粗的普通文本" />)
    expect(container.querySelector('strong')).toBeNull()
    expect(screen.getByText('没有任何加粗的普通文本')).toBeInTheDocument()
  })

  it('一段里多个加粗都被识别', () => {
    const { container } = render(<SimpleMarkdown text="**甲** 与 **乙** 都重要" />)
    const strongs = container.querySelectorAll('strong')
    expect(strongs).toHaveLength(2)
    expect(strongs[0].textContent).toBe('甲')
    expect(strongs[1].textContent).toBe('乙')
  })
})
