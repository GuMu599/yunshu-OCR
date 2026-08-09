---
name: yunshu-ocr
description: Use when reading or extracting content from a PDF file — answering questions, summarizing, searching, comparing, or citing passages from a PDF. Use when a PDF is referenced, attached, or opened and its content matters, and a token-efficient Markdown version could avoid reading the binary PDF directly.
---

# yunshu-ocr — PDF→Markdown 绑定读取

## Overview

**核心原则：AI 读 Markdown，用户操作 PDF。** PDF 是用户看到的原始视觉来源；AI 应优先读本仓库 `pdf2md` 转换出的 Markdown（省 token）。`layout.json` 提供逐元素的 PDF 页/bbox 溯源（绑定），只有 Markdown 不足以回答时，才按需渲染 PDF 局部。

## When to Use

- 需要读取/提取/回答 PDF 内容时（总结、搜索、对比、引用）。
- 用户贴出 PDF 路径或打开 PDF 时。
- 当整本读 PDF 二进制 token 成本过高时。

**不要用**：仅当用户明确要操作 PDF 本身（标注、截图整页）时，才直接读 PDF。

## Core Workflow

### 1. 确保转换缓存（一次）

```bash
python .claude/skills/yunshu-ocr/pdf2md.py ensure "<pdf>"
```

- 输出 JSON：`md` / `layout` / `report` / `stats` / `cached`。
- 缓存放 PDF 旁 `<name>_pdf2md/`，按 PDF mtime 复用；`--force` 重转。
- 转换失败（`ok:false`）→ 回退直接读 PDF，不要卡住。

### 2. 读 Markdown（主路径）

读 `md` 路径的 `.md` 文件。这是 token 高效的表示：
- 表格是 MD 表格（含 `<!-- table: full structure in layout.json -->` 标记 → 完整 HTML 在 layout.json）
- 公式是 ` ```latex ` 代码块
- 图片是 `![...](images/...)` 引用

### 3. 绑定溯源（按需）

需要知道某内容在 PDF 哪一页/哪一区域时，读 `layout.json`：
`elements[].items[]` 有 `page`、`bbox_pdf`、`type`、`content_type`、`markdown`。
据此回答"这段话在第几页"、定位具体元素。

### 4. 按需渲染 PDF 局部（仅当 MD 不足）

MD 中降级的内容（`table_image`、`![formula]`、低置信公式、覆盖率低的页）才渲染：

```bash
python .claude/skills/yunshu-ocr/pdf2md.py render "<pdf>" <page> "x0,y0,x1,y1" --dpi 300 --out /tmp/region.png
```

- bbox 从 layout.json 取；只渲染 bbox 区域，绝不整页全图读。
- 渲染后 Read 该 PNG。

### 5. 检查转换状态

```bash
python .claude/skills/yunshu-ocr/pdf2md.py info "<pdf>"
```

## Quick Reference

| 需求 | 动作 |
|---|---|
| 读内容 | `ensure` → 读 `.md` |
| 内容在 PDF 哪页 | 读 `layout.json` 的 `page`/`bbox_pdf` |
| 表格退化/公式不确定 | `render` 该 bbox 读原文 |
| 转换是否最新 | `info`（mtime 自动判断） |
| 强制重转 | `ensure --force` |

## Common Mistakes

- **整本读 PDF**：除非 MD 完全不足，否则只读 MD + 按需渲染局部。
- **重复转换**：`ensure` 已按 mtime 缓存，不要手动重跑 CLI。
- **忽略 layout.json**：绑定是现成的，不要凭印象猜页码。
- **渲染整页**：用 bbox 只渲染目标区域，省 token。

## Helper

- `pdf2md.py`（本技能目录）：`ensure` / `render` / `info` 子命令，输出 JSON。
- 底层工具：`python -m pdf2md.cli`（转换）、`pdf2md/benchmark.py`（质量基准）、`pdf2md/lint.py`（输出 lint）。
