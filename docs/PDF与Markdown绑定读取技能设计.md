# PDF↔Markdown 绑定读取工具设计

> 状态：已实现。使用说明见 [`tools/pdf-reading/README.md`](../tools/pdf-reading/README.md)，辅助脚本为同目录 `pdf2md.py`。
> 本文是设计溯源与后续演进基线。

## 目标

**AI 读 Markdown，用户操作 PDF。** 最终形态：AI 在需要处理 PDF 时，先唤醒本工程将 PDF 转成规范化 Markdown 并建立绑定，然后**只读 Markdown**（省 token）；只有 Markdown 不足以回答时才按需渲染 PDF 局部。用户始终以 PDF 为操作对象，AI 以 Markdown 为阅读对象。

```
用户: "看看这篇论文里表 1 的数据"        ← 用户操作对象是 PDF
  │ 启动处理流程
  ▼
AI:  ensure <pdf> (缓存复用) → 读 <name>.md        ← AI 阅读对象是 Markdown
  │  表 1 在 layout.json 有 page+bbox 溯源 → 直接回答
  │  (若表退化为图片) → render 该 bbox 局部读原文
```

## 为什么省 token

- 读 MD 是纯文本，token 成本远低于把 PDF 整本渲染/读二进制。
- 表格/公式/扫描页都被结构化成文本（表格 MD、` ```latex `、OCR 文本）。
- 只有"降级内容"（`table_image`、公式兜底图、低覆盖率页）才按需渲染 PDF 局部，且只渲染 bbox 区域，不整页。

## 机制

### 1. 转换缓存（一次，复用）

- 缓存位置：**PDF 旁** `<name>_pdf2md/`（与 `pdf2md` 默认输出一致），文档随身走。
- 复用判据：MD 存在且 `mtime(pdf) ≤ mtime(md)`；`--force` 强制重转。
- 产物：`<name>.md`（主）、`layout.json`（溯源绑定）、`report.json`（统计）、`images/`。

### 2. 绑定（溯源）

`layout.json` 已是现成绑定：`elements[].items[]` 每个元素带 `page` + `bbox_pdf` + `type` + `markdown`。
AI 据此回答"某内容在第几页/哪个区域"，并在需要时精确渲染。

### 3. 按需渲染 PDF 局部

```bash
python tools/pdf-reading/pdf2md.py render "<pdf>" <page> "x0,y0,x1,y1" --dpi 300 --out /tmp/region.png
```

- bbox 取自 layout.json；只渲染目标区域，不整页。
- 仅当 MD 不足以回答时触发（降级表、公式不确定、覆盖率低）。

## 工具结构

- `tools/pdf-reading/README.md`：适用场景、工作流、安全边界和常见错误。
- `tools/pdf-reading/pdf2md.py`：`ensure` / `info` / `render` 子命令，输出 JSON 供 AI 解析。

## 约束（写进技能）

1. **优先 MD**：AI 默认只读 MD，绝不整本读 PDF。
2. **绑定优先**：溯源用 layout.json，不凭印象猜页码。
3. **按需渲染**：仅降级内容渲染，且只渲染 bbox。
4. **缓存复用**：`ensure` 已按 mtime 处理，不重复手动转换。
5. **失败兜底**：转换失败 → 直接读 PDF，不阻塞。

## 与现有基础设施的关系

| 组件 | 角色 |
|---|---|
| `python -m pdf2md.cli` | 转换引擎（阅读工具底层调用） |
| `layout.json` | PDF↔MD 绑定（溯源） |
| `report.json` | 统计/覆盖率（判断是否需按需渲染） |
| `pdf2md/benchmark.py` | 转换质量基准（确保 MD 可靠） |
| `pdf2md/lint.py` | 输出质量 lint |

## 后续演进（非本期）

- **双向锚点**：MD 段落 ↔ PDF 页/bbox 的显式索引（现在是逐元素隐含绑定），支持"从 AI 回答一键跳到 PDF 位置"。
- **多页/跨页表格绑定**：跨页合并后的表格溯源到起止页。
- **增量缓存**：PDF 局部变更只重转受影响页。
- **工具自检**：`info` 返回覆盖率，覆盖率异常时自动提示按需渲染。
- **跨项目复用**：可复制 `tools/pdf-reading/`，并保持相对于仓库根目录的目录层级。
