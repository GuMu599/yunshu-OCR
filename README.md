# yunshu-OCR

独立、离线、零 token 的 PDF OCR 与 PDF→Markdown 工具集。

本仓库由两个协同组件组成，均可单独使用：

| 组件 | 目录 | 职责 |
|---|---|---|
| **OCR 工具集** | `tools/` + `models/` | 对 PDF 区域跑 OCR（子进程隔离、内存/时间上限），用原生文本诊断判断是否需要 OCR |
| **pdf2md** | `pdf2md/` | 把 PDF 转成规范化 Markdown，供任意 AI 直接消费，全链路离线、**不消耗任何 LLM token** |

核心思路沿自 litwise 文献阅读家族：**原始 PDF 是不可变的视觉来源，OCR 只用来补救原生文本失败的区域**，公式/表格/图片用版面检测 + 专用模型恢复。

---

## 特性

- **OCR 工具集**
  - 独立子进程运行 OCR，监控 RSS 与超时，崩溃/超内存不拖垮宿主进程
  - 结果带页码、PDF 坐标、置信度，序列化契约稳定（`OCRRegionRequest` / `OCRCandidate` / `OCRJobResult`）
  - 页面诊断：用 PyMuPDF 原生文本判断每页走 `native` / `ocr` / `manual_review`
  - 生产 RapidOCR 适配器（onnxruntime CPU，中文 PP-OCRv4 权重约 16MB 随目录落地）
- **pdf2md**
  - 全离线转换，不消耗任何 LLM token
  - 版面检测（doclayout_yolo）→ 文字/图片/表格提取 → 内容分类 → 阅读顺序 → 规范化 Markdown
  - 公式识别：pix2tex（图像→LaTeX）优先，缺失时自动回退 RapidOCR + 符号映射
  - 输出自带溯源（`layout.json`）与转换报告（`report.json`）

---

## 项目结构

```text
yunshu-OCR/
├── README.md                     # 本文件
├── requirements.txt              # OCR 工具集依赖
├── .gitignore                    # 排除 __pycache__、模型权重、测试数据
│
├── tools/                        # ◀ 组件一：OCR 工具集
│   ├── ocr_worker.py             #   子进程 OCR worker（RSS/超时监控）
│   ├── ocr_contracts.py          #   序列化契约（请求/候选/结果）
│   ├── page_diagnostics.py       #   页面信号提取与状态诊断
│   └── resource_limits.py        #   内存/DPI/批量页资源策略
│
├── models/production/
│   └── rapidocr-adapter/         #   vendored RapidOCR 适配器（v3.4.x, onnxruntime）
│       └── rapidocr/models/      #   PP-OCRv4 det/rec + cls onnx 权重、字典、字体
│
├── pdf2md/                       # ◀ 组件二：PDF→Markdown
│   ├── cli.py                    #   CLI 入口
│   ├── pipeline.py               #   转换主链路
│   ├── layout.py                 #   版面检测（doclayout_yolo）
│   ├── text.py / tables.py       #   文字、表格提取
│   ├── classify.py / order.py    #   内容分类、阅读顺序/页眉页脚
│   ├── formulas.py               #   公式识别（pix2tex 优先）
│   ├── ocr.py                    #   OCR 兜底（复用 vendored 适配器）
│   ├── normalize.py / lint.py    #   Markdown 规范化与质量 lint
│   ├── sidecar.py / textloss.py  #   溯源与文字不丢失检测
│   └── README.md                 #   组件独立文档（输出契约、实测结果）
│
├── scripts/
│   └── ocr_demo.py               # OCR 真实输出检测 demo
│
├── tests/                        # OCR 工具集测试（10 个）
├── pdf2md/tests/                 # pdf2md 测试（22 个）
│
└── docs/
    ├── OCR流程完整说明.md           # OCR 流程、置信度门禁、排错
    └── PDF转Markdown零token工具实现计划.md
```

---

## 环境要求

- Python **3.10+**（已在 3.13 验证）
- Windows / Linux / macOS
- CPU 即可（onnxruntime CPU 推理）；GPU 可选但非必需

---

## 安装

```powershell
cd E:\Codex\yunshu-OCR

# OCR 工具集依赖
pip install -r requirements.txt

# pdf2md 额外依赖（版面检测 + 公式识别）
pip install -r pdf2md/requirements.txt
```

> **模型权重说明**：RapidOCR 的 `.onnx` 权重（约 16MB）已在本地 `models/production/rapidocr-adapter/rapidocr/models/` 下，开箱即可跑真实 OCR。权重通过 `.gitignore` 排除、**不提交 git**，拷贝/克隆仓库时需一并带上该目录；也可用环境变量 `LITWISE_RAPIDOCR_ADAPTER` 指向其他 RapidOCR 适配器目录。

---

## 使用方法

### 组件一：OCR 工具集（`tools/`）

#### A. Python API — 直接对 PDF 区域做 OCR

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

from ocr_contracts import OCRRegionRequest
from ocr_worker import run_ocr_job

request = OCRRegionRequest(
    job_id="manual-p1",
    pdf_path=r"E:\papers\sample.pdf",
    page=1,
    regions=[[40.0, 100.0, 560.0, 740.0]],  # PDF 坐标 bbox
    engine="production",                     # 或 "fake" 用于无模型环境测试
    language="zh",
    dpi=220,
    max_ram_bytes=8 * 1024**3,
)

result = run_ocr_job(request, timeout_seconds=120)
for item in result.regions:
    print(item.text, item.confidence, item.bbox_pdf)
print(result.error, result.peak_rss_bytes, result.duration_ms)
```

#### B. Python API — 页面诊断（判断是否触发 OCR）

```python
from page_diagnostics import extract_page_signals, diagnose_page

signals = extract_page_signals(r"E:\papers\sample.pdf")
for signal in signals:
    result = diagnose_page(signal)
    print(signal.page, result.status, result.reasons, result.repair_regions)
```

#### C. 命令行 Demo

```bash
python scripts/ocr_demo.py <pdf路径> [页码...] [--output 目录]
```

不带页码：对全文逐页做页面诊断，汇总状态分布；带页码：额外对指定页跑真实 RapidOCR，输出识别文本、置信度、耗时与峰值内存。结果写到 `<pdf名>.ocr.json` 与 `<pdf名>.ocr.md`。

### 组件二：pdf2md（`pdf2md/`）

#### A. CLI 转换

```bash
python -m pdf2md.cli <input.pdf> --output <out>
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--output` | 输入同目录 `<name>_pdf2md` | 输出目录 |
| `--lang` | en | zh / en |
| `--drop-margins` | 保留 | 删除页眉页脚（默认标注保留） |
| `--no-ocr` | 关 | 跳过 OCR 兜底 |
| `--formula-engine` | auto | auto / pix2tex / rapidocr |
| `--dpi` / `--formula-dpi` / `--image-dpi` | 220 / 300 / 200 | OCR / 公式 / 图片 DPI |
| `--max-pages` | 全部 | 只处理前 N 页 |

#### B. 输出契约

每个 PDF 产出：

```text
<out>/
├── <name>.md        # 唯一最终产物
├── images/          # 图片单独存放，MD 相对路径引用
├── layout.json      # 溯源：逐页元素 + bbox + 页眉页脚 + 降级标记
└── report.json      # 转换报告（指标 / 覆盖率 / 元数据）
```

`<name>.md` 结构：顶部 `> 元数据块` → `## Page N` 分页 → 正文 / `` ```latex `` 公式代码块 / MD 表格 / `![figure](images/…)` / `<!-- header -->…<!-- /header -->` 页眉页脚标注保留。

#### C. 质量检查

```bash
python -m pdf2md.lint <生成的.md>   # 已知失败模式 lint（目录标题/正文标题/公式合并/公式乱码）
python -m pytest pdf2md/tests/      # pdf2md 单元测试
```

完整参数、实测结果与已知限制见 [`pdf2md/README.md`](pdf2md/README.md)。

---

## 测试

```powershell
# 全量（32 个测试）
python -m pytest tests/ pdf2md/tests/

# 按组件
python -m pytest tests/          # OCR 工具集（10 个）
python -m pytest pdf2md/tests/   # pdf2md（22 个）
```

---

## 文档

- [`docs/OCR流程完整说明.md`](docs/OCR流程完整说明.md) — OCR 工具集完整流程、置信度门禁与排错
- [`docs/PDF转Markdown零token工具实现计划.md`](docs/PDF转Markdown零token工具实现计划.md) — pdf2md 设计决策与输出契约

---

## 开源致谢

本仓库的代码源自内部 litwise 文献阅读家族项目的提取与合并；第三方能力直接复用以下开源项目，在此致谢：

### 直接复用的核心组件

| 开源项目 | 版本 | 用途 | License |
|---|---|---|---|
| **RapidOCR** | vendored v3.4.x | 中文/英文 OCR 推理后端（`models/production/rapidocr-adapter/`，onnxruntime CPU） | Apache-2.0 |
| **PaddleOCR（PP-OCRv4 模型）** | det / rec / cls | 检测、识别、方向分类的 `.onnx` 权重（随适配器落地） | Apache-2.0 |
| **doclayout_yolo** | ≥ 0.0.2b1 | PDF 版面检测（`pdf2md/layout.py`，YOLOv10 派生） | Apache-2.0 |
| **pix2tex / LaTeX-OCR** | ≥ 0.1.4 | 公式图片→LaTeX（`pdf2md/formulas.py`，可选，缺失自动回退） | MIT |
| **PyMuPDF（MuPDF/fitz）** | ≥ 1.23.0 | PDF 渲染与文字/图片提取（`tools/`、`pdf2md/text.py`） | AGPL-3.0 |
| **ONNX Runtime** | ≥ 1.17.0 | RapidOCR 的推理执行引擎 | MIT |

### 运行时依赖

`numpy`（BSD-3）、`opencv-python`（Apache-2.0）、`Pillow`（HPND）、`omegaconf`（BSD-3）、`pyclipper`（MIT）、`shapely`（BSD-3）、`colorlog`（MIT）、`requests`（Apache-2.0）、`tqdm`（MIT）、`psutil`（BSD-3）、`pytest`（MIT）。

### 模型与字体

- `.onnx` 权重由 RapidAI 从 PaddleOCR 导出，按 Apache-2.0 条款随 RapidOCR 分发。
- `FZYTK.TTF`（方正姚体）由 RapidOCR 随包分发，仅用于识别结果可视化，字体版权归其原持有人所有，使用请遵守原授权。
- pix2tex 权重首次运行时从 HuggingFace 下载（约 90M，一次性）。

> **许可提示**：本仓库本身尚未声明独立 License；其中直接复用/改写的代码与模型应分别遵循上表所列原项目的授权条款（如 PyMuPDF 为 AGPL-3.0），对外发布前请评估衍生作品的合规要求。

---

## 已知限制

- 当前只有 RapidOCR 单模型，系统置信度上限 0.94，低置信度结果需人工复核。
- 复杂表格、公式和部分旧式扫描件可能无法自动恢复（OCR 兜底页带 `<!-- ocr:page -->` 标记供复核）。
- 公式主引擎 pix2tex 对等式编号、`v/y/ν` 等偶有误读；RapidOCR 兜底是"近似 LaTeX"。
- 图片型表格无法转 MD，降级为表格图片；真实有框文字表可转 MD。
- 跨页表格 v1 不合并。
