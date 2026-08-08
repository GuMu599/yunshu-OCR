# pdf2md — 零 token 离线 PDF→Markdown

把 PDF 转成**规范化 Markdown** 供后续任意 AI 直接消费。**转换全链路离线、不消耗任何 LLM token。**

复用 litwise 家族既有资产：doclayout_yolo 版面、PyMuPDF 文字/图片/表格、RapidOCR 兜底。

## 输出契约（每个 PDF 产出）

```text
<out>/
├── <name>.md        # 唯一最终产物
├── images/          # 图片单独存放, MD 相对路径引用
├── layout.json      # 溯源: 逐页元素 + bbox + 页眉页脚 + 降级标记
└── report.json      # 转换报告 (指标/覆盖率/元数据)
```

`<name>.md` 结构：顶部 `> 元数据块` → `## Page N` 分页 → 正文 / ```latex 公式代码块 / MD 表格 / `![figure](images/…)` / `<!-- header -->…<!-- /header -->` 页眉页脚标注保留。

## 用法

```bash
cd E:\Codex\yunshu-OCR
python -m pdf2md.cli <input.pdf> --output <out>
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--output` | 输入同目录 `<name>_pdf2md` | 输出目录 |
| `--lang` | en | zh / en |
| `--drop-margins` | 保留 | 删除页眉页脚（默认标注保留） |
| `--no-ocr` | 关 | 跳过 OCR 兜底 |
| `--dpi` / `--formula-dpi` / `--image-dpi` | 220/300/200 | OCR / 公式 / 图片 DPI |
| `--max-pages` | 全部 | 只处理前 N 页 |

## 质量检查

```bash
python -m pdf2md.lint <生成的.md>   # 已知失败模式 lint (目录标题/正文标题/公式合并/公式乱码)
python -m pytest pdf2md/tests/       # 22 个单元测试
```

## 实测结果（2026-08-08，真实语料）

| 语料 | 页数 | 耗时 | 文字不丢失 | 元数据 | 公式 | 表格 | 页眉 |
|---|---|---|---|---|---|---|---|
| Blundell《Magnetism in Condensed Matter》前25页 | 25 | 57s | 全部 OK（每页 MD≥原生） | 标题/年份/作者 ✓ | 27 个 ` ```latex `（11 不确定） | 0 MD + 10 图片 | "N Introduction" 6 页已标注 |
| 曲波涛《…锌配位聚合物…》中文期刊 | 8 | 17s | 全部 OK | 标题/年份 ✓ | 2 个 | 0 MD + 2 图片 | 无 |

真实输出样本（Blundell 第18页，文字层不可见的显示公式被空隙检测器恢复）：

```latex
M = xH, (1.18)
B = \muo(1 + x)H = \muo\murH, (1.19)   # 下标拍平, 数学结构可读
```

## 公式引擎

默认 `--formula-engine auto`：**pix2tex (LaTeX-OCR)** 优先，直接输出真 LaTeX
（分数/下标/矩阵/希腊字母/积分均正确）；不可用时自动回退 RapidOCR + 符号映射。
pix2tex 权重首次运行从 HuggingFace 下载（约 90M，一次性）。CPU 上每条公式约 1-3s。

## 已知限制（诚实记录）

- 公式主引擎 pix2tex（图像→LaTeX）。残余问题：等式编号偶被读成 `\mathbf{Q.NN}` 类伪影、
  `v/y/ν` 偶混、个别新符号误读；RapidOCR 兜底仍是"近似 LaTeX"（`χ→x`、下标拍平）。
  不确定项与降级图都记在 layout.json。
- 老式 LaTeX 排版的 PDF 数学字形 unicode 映射损坏，**文字层完全不可见**；靠"文字块空隙检测器"视觉恢复，只对跨 ≥3 页重复的页眉、间隙内墨迹有效。
- **图片型表格无法转 MD**（两语料的真实数据表在 PDF 里就是图片），降级为表格图片；真实有框文字表可转 MD（find_tables lines 策略）。
- YOLO 版面分类对这本书噪声大（散文/图注被误判为 table/formula），已用内容启发式（文字行长度、数学符号、图注前缀、去重）补偿。
- 跨页表格 v1 不合并。
- RapidOCR 对英文会丢空格（`Magnetismin`），OCR 页标记 `<!-- ocr:page -->` 供人工复核。
- texify 权重因 HF 不可达无法下载，未接入；模型可用后为公式升级路径。
