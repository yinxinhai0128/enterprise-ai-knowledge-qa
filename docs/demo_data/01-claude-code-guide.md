# Claude Code 使用指南

## 概述

Claude Code 是 Anthropic 开发的官方 CLI（命令行接口）工具，专为软件工程任务设计。
它以 AI 为核心，能够理解代码上下文、修改文件、执行命令、搜索代码库。与传统代码补全
工具不同，Claude Code 拥有完整的文件系统访问权限，可以跨多个文件进行一致性修改。

## 核心功能

### 代码理解与修改

- 读取整个代码库，理解架构和依赖关系
- 精确编辑文件（只发送 diff，不重写整个文件）
- 支持多文件同时修改，保证一致性
- 通过 Glob、Grep、Read 工具精准定位代码位置

### 命令执行

- 运行测试、构建、lint、格式化
- 执行 git 操作（commit、push、PR 创建）
- 管理包依赖（npm install、pip install）
- PowerShell（Windows）或 Bash（macOS/Linux）均支持

### 多 Agent 并行策略

Claude Code 支持同时启动多个 Agent 协同工作：

```
主控 Agent（主线程）
├─ 制定契约：定义接口规范、成功标准
├─ 派发执行 Agent → worktree 隔离实现功能
├─ 派发检查 Agent → 独立验收（不共享上下文）
└─ 整合结果 → commit/push
```

**角色分工原则**：
- 主控不亲自写实现代码（避免自改自查）
- 执行 Agent 在 worktree 隔离分支中工作
- 检查 Agent 独立冷启动，只读不改

### 技能系统（Skills）

技能是预配置的工作流，存储在 `~/.claude/skills/` 目录：

| 技能名 | 用途 |
|--------|------|
| `playwright` | 驱动真实浏览器做 UI 自动化、截图、表单填写 |
| `pdf` | PDF 文档生成与内容提取 |
| `multi-agent-harness` | 并行多 Agent 协同策略 |
| `huashu-design` | 高保真 HTML 原型与交互 Demo |
| `code-review` | 代码评审，支持内联注释 |
| `verify` | 运行应用验证功能是否按预期工作 |

调用技能：在聊天中输入 `/skill-name` 即可激活。

## 常用指令

| 指令 | 作用 |
|------|------|
| `/model` | 切换 AI 模型（sonnet/opus/haiku） |
| `/clear` | 清除对话上下文 |
| `/fast` | 切换快速模式（更快响应） |
| `/review` | 代码评审 |
| `/help` | 显示帮助信息 |
| `/init` | 初始化 CLAUDE.md 文件，记录代码库文档 |

## 工具说明

Claude Code 内置以下工具，每次调用对应一次权限提示：

| 工具 | 说明 |
|------|------|
| `Read` | 读取文件内容（支持 PDF、Jupyter Notebook、图片） |
| `Write` | 创建或完整覆盖文件 |
| `Edit` | 精确字符串替换，只发送 diff |
| `Glob` | 按模式查找文件（如 `**/*.py`） |
| `Grep` | 正则搜索文件内容（基于 ripgrep） |
| `Bash` | 执行 bash 命令（POSIX 语法） |
| `PowerShell` | 执行 PowerShell 命令（Windows） |
| `Agent` | 派发子 Agent 执行复杂多步任务 |

## 最佳实践

### 安全原则

1. **先读再改**：每次修改前必须用 Read 工具读取文件内容
2. **禁止凭记忆写 API**：库的 API 会随版本变化，必须查看实际代码
3. **不跳过钩子**：`--no-verify` 等绕过检查的选项需要用户明确要求
4. **不强制推送**：禁止 `git push --force` 到 main/master，会提示用户

### 效率原则

1. **并行工具调用**：无依赖关系的操作可以同时执行（多个 Read、Grep 并行）
2. **精确路径**：引用代码时带上 `file_path:line_number`
3. **最小变更**：不添加超出任务要求的功能或抽象
4. **直接工具优先**：已知路径用 Read，已知符号用 Grep，不到万不得已不用 Agent

### 注释原则

- 默认不写注释（好的命名就是最好的文档）
- 只在"为什么"非显而易见时加一行注释
- 不写"这段代码做了 X"式的描述性注释

## 适用场景

### 解决 Bug

提供错误日志和相关文件路径，Claude Code 会定位根因并修复，同时检查是否有同类问题。

### 添加新功能

描述需求，Claude Code 会问必要细节，然后跨多个文件一致性地实现功能。

### 代码重构

Claude Code 保持功能不变的前提下改善结构，并运行测试验证结果。

### 探索代码库

"找到所有处理认证的文件"——Claude Code 会系统性地搜索并返回相关位置。

### 代码审查

"检查这个 PR 是否有安全问题"——输出精确的 diff 位置和改进建议。

## 配置文件

| 文件 | 说明 |
|------|------|
| `~/.claude/settings.json` | 全局配置（权限、模型、钩子） |
| `.claude/settings.json` | 项目配置（优先级高于全局） |
| `CLAUDE.md` | 项目文档，自动注入到每次对话上下文 |
| `~/.claude/keybindings.json` | 键盘快捷键自定义 |

## 版本说明

Claude Code 运行在 Claude 模型上（Sonnet、Opus、Haiku），具体模型 ID 请通过
`/model` 命令或官方文档确认，不同模型在速度、成本和能力上有所差异。
