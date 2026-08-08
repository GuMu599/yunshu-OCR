# OCR 工具集完整流程说明

本文档描述本仓库 `tools/` 下 **OCR 工具集**的实际实现：PDF 页面诊断（是否/哪里需要 OCR）、隔离子进程运行 OCR、输入输出契约、资源限制、置信度校准、错误码与排错。

适用目录：

```text
E:\Codex\yunshu-OCR
```

文档基于当前源码（`tools/`）与测试整理。代码行为优先；若文档与代码不一致，以代码和测试为准并更新本文档。

> 本工具集只解决「对 PDF 区域跑 OCR」这一个小问题；PDF→Markdown 的版面/公式/表格能力在 `pdf2md/` 组件，见 [`pdf2md/README.md`](../pdf2md/README.md)。

---

## 1. 先看结论：完整链路

默认不是「所有页面都 OCR」。原始 PDF 是不可变的视觉来源，OCR 只用来补救**原生文本失败的区域**。

```text
PDF
  -> extract_page_signals()          # PyMuPDF 逐页提取原生文本/几何/图片信号
  -> diagnose_page(signals)          # 决策：native_pass / ocr_required / manual_review
  -> run_ocr_job(request)            # （仅 ocr_required）独立子进程执行
       ├─ OCRRegionRequest（页码 + bbox 区域 + 引擎 + DPI + 内存上限）
       └─ python tools/ocr_worker.py --worker   # 一行 JSON 请求 -> 一行 JSON 结果
  -> RapidOCR 适配器（production/rapidocr）或 fake 测试引擎
  -> _calibrate_ocr_confidence()     # 置信度封顶 0.94，乱码惩罚
  -> OCRJobResult（候选 + 退出码 + 峰值 RSS + 耗时 + 错误）
```

关键原则：

1. OCR 结果必须带页码和 PDF 坐标（bbox），不允许只有一段无定位文本。
2. OCR worker 在独立子进程中运行，超过时间或内存上限会被终止并返回显式错误，不拖垮宿主进程。
3. 单模型置信度最高封顶 `0.94`；低置信度结果由调用方决定是否人工复核。
4. 模型和 OCR 依赖不在宿主进程直接加载，通过 worker 调用生产适配器。

---

## 2. 模块总览

| 文件 | 作用 |
|---|---|
| `tools/ocr_contracts.py` | 定义 `OCRRegionRequest`、`OCRCandidate`、`OCRJobResult` 三个序列化契约。 |
| `tools/ocr_worker.py` | `run_ocr_job()` 启动隔离子进程并监控 RSS/超时；文件同时可作为 `--worker` 子进程入口。 |
| `tools/page_diagnostics.py` | `extract_page_signals()` / `diagnose_page()`：判断每页走 native / OCR / manual_review。 |
| `tools/resource_limits.py` | `ResourcePolicy`：内存、批量页、DPI 资源策略。 |
| `models/production/rapidocr-adapter` | vendored RapidOCR 适配器；`.onnx` 权重被 `.gitignore` 忽略，属于本机运行时。 |
| `scripts/ocr_demo.py` | 命令行 demo：逐页诊断 + 对指定页跑真实 OCR 并输出报告。 |

默认适配器路径：

```text
<repo_root>\models\production\rapidocr-adapter
```

可通过环境变量覆盖：

```powershell
$env:LITWISE_RAPIDOCR_ADAPTER = "E:\other\rapidocr-adapter"
```

若该目录不存在、没有 `rapidocr` 包目录，或 `from rapidocr import RapidOCR` 失败，worker 返回 `model_missing:rapidocr`。

---

## 3. 页面诊断：什么时候会触发 OCR

文件：`tools/page_diagnostics.py`

### 3.1 `DiagnosticPolicy` 默认阈值

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `min_native_characters` | `400` | 原生字符数低于 400 → 原生保留不足。 |
| `min_valid_character_ratio` | `0.97` | 有效字符比例低于 97% → 文本损坏。 |
| `max_replacement_ratio` | `0.002` | `U+FFFD` 替换字符比例超过 0.2% → 损坏。 |
| `max_control_character_ratio` | `0.002` | 非换行/制表控制字符比例超过 0.2% → 损坏。 |
| `max_overlap_ratio` | `0.08` | 文本 bbox 重叠占比超过 8% → 记录版式异常（单独不强制 OCR）。 |

### 3.2 `extract_page_signals(pdf_path)`

对每一页用 PyMuPDF `page.get_text("rawdict")` 生成 `PageSignals`：

| 字段 | 说明 |
|---|---|
| `page` / `width` / `height` | 页码（1 起）与页面尺寸。 |
| `native_characters` | 原生字符总数。 |
| `valid_character_ratio` | 有效字符比例。 |
| `replacement_ratio` | `U+FFFD` 替换字符比例。 |
| `control_character_ratio` | 控制字符比例。 |
| `text_coverage` / `image_coverage` | 文本 / 图片 bbox 覆盖率（0..1）。 |
| `overlap_ratio` | 文本块重叠面积占比。 |
| `block_count` | 文本块数量。 |
| `crossed_reading_edges` | 同列文本上下顺序交叉数。 |
| `suspicious_regions` | 含替换字符或控制字符的原生文本块 bbox 列表。 |
| `column_count` | 粗略列数提示。 |
| `native_elements` | 原生元素：文本、bbox（PDF 与归一化）、字体名/字号/颜色、行数、列提示、来源。 |

### 3.3 `diagnose_page()` 决策顺序

```python
signals 存在文字损坏（low_native_retention / replacement_characters / control_characters 任一）
├─ 无损坏                     -> native_pass，repair_regions = []
├─ 有损坏且 suspicious_regions 非空
│                            -> ocr_required，只修复这些区域
├─ 有损坏、无明确区域，但 image_coverage >= 0.5 或 native_characters < 400
│                            -> ocr_required，整页 bbox [0, 0, width, height]
└─ 其他无法安全自动恢复       -> manual_review，repair_regions = []
```

返回 `PageDiagnostic(page, status, reasons, repair_regions, metrics)`。

含义：

- **native_pass**：原生文本干净，不启动 OCR。
- **ocr_required**：只对 `repair_regions` 启动 OCR——是「按区域修复」，不是整页覆盖。
- **manual_review**：无法安全自动恢复，需要人工复核。

页面若只有阅读顺序/重叠等版式问题而文本本身干净，仍走 `native_pass`（布局问题由调用方自行处理，本工具集不重排文本）。

---

## 4. OCR 请求契约

文件：`tools/ocr_contracts.py`

```python
OCRRegionRequest(
    job_id: str,            # 调试追踪用，如 "manual-p1"
    pdf_path: str,          # 原始 PDF 绝对路径
    page: int,              # 从 1 开始的页码
    regions: list[list[float]],   # PDF 坐标 bbox，格式 [x0, y0, x1, y1]
    engine: str,            # "fake" | "production" | "rapidocr"
    language: str,          # 入参存在；适配器目前按模型默认语言工作，不据此切换
    dpi: int,               # 区域渲染 DPI
    max_ram_bytes: int,     # worker 峰值 RSS 上限
)
```

`engine` 取值：

- `fake`：不执行真实 OCR，对每个区域返回固定文本 `fake ocr text`（置信度 1.0），用于验证 worker 生命周期、JSON 协议，无模型环境测试用。
- `production` / `rapidocr`：都走 vendored RapidOCR 适配器。
- 其他值：worker 返回 `unsupported_engine:<name>`，退出码 2。

---

## 5. OCR worker 生命周期

文件：`tools/ocr_worker.py`

```python
run_ocr_job(request: OCRRegionRequest, timeout_seconds: float = 120) -> OCRJobResult
```

执行行为：

1. 创建临时文件承接 worker stdout（文件背板，避免 Windows 大 JSON 走管道死锁）。
2. 启动子进程 `python tools/ocr_worker.py --worker`，`stderr` 丢弃。
3. 把 `request.to_dict()` 序列化为**单行 ASCII 转义 JSON**，通过 stdin 发送。
4. 父进程每 20ms 轮询子进程，记录峰值 RSS。
5. 峰值 RSS 超过 `max_ram_bytes` → `resource_limit_exceeded`；总时长超过 `timeout_seconds` → `timeout`。
6. 超限时终止 worker 及其所有递归子进程。
7. 读取 stdout 最后一行 JSON，解析为 `OCRJobResult`。

worker 侧把第三方 OCR 库的 stdout 重定向到 `os.devnull`，stdout 只保留协议 JSON。

### 5.1 `OCRJobResult`

```python
OCRJobResult(
    regions: list[OCRCandidate],
    worker_pid: int | None,
    worker_exit_code: int,
    worker_alive_after_join: bool,
    peak_rss_bytes: int,
    duration_ms: int,
    error: str | None = None,
)
```

调用方必须重点检查：

- `worker_exit_code == 0`
- `worker_alive_after_join is False`
- `error is None`
- `regions` 非空
- `peak_rss_bytes` 未超过请求上限

### 5.2 `OCRCandidate`

```python
OCRCandidate(
    bbox_pdf: list[float],
    text: str,
    confidence: float,
    engine: str,
    character_confidences: list[float] = [],
)
```

RapidOCR 只能稳定提供行级分数，因此 `character_confidences` 为空列表——**不要**把它解释成逐字符已验证。

---

## 6. 生产 RapidOCR 路径

`ocr_worker._run_rapidocr()`：

1. 读取 `LITWISE_RAPIDOCR_ADAPTER`，缺省用 `<repo_root>/models/production/rapidocr-adapter`。
2. 校验适配器目录下存在 `rapidocr` 包，缺则返回 `model_missing:rapidocr`。
3. 把适配器目录加入 `sys.path`，导入 `fitz` 和 `RapidOCR`。
4. 打开 PDF，加载 `page - 1`。
5. 对每个 region 与页面矩形求交集，空区域直接跳过。
6. 用 `fitz.Matrix(max(1, dpi/72), max(1, dpi/72))` 按 DPI 渲染区域 PNG。
7. 调用 `RapidOCR()(png_bytes)`，合并识别行文本；空文本区域跳过。
8. 行分数取均值，进入 `_calibrate_ocr_confidence()` 校准。
9. 每个区域输出 `OCRCandidate(engine="rapidocr", character_confidences=[])`。

任何 PDF 打开/渲染/模型调用异常返回 `rapidocr_failed:<前 200 字符>`，退出码 2。

---

## 7. 置信度校准

`_calibrate_ocr_confidence(text, raw_confidence)`：

1. 统计 `U+FFFD` 与可疑乱码 token（`锟`、`烫烫` 等）。
2. 计算损坏字符占可见文本比例 `damage_ratio`。
3. 单模型不自我验证学术文本：`calibrated = min(raw, 0.94) * (1 - damage_ratio * 8)`。
4. 结果限制在 `0..0.94`，保留 4 位小数。

因此即使 RapidOCR 原始分数为 0.99，单模型结果也不会超过 0.94 的系统置信度。

---

## 8. 资源限制与超时

### 8.1 `run_ocr_job` 参数

```python
run_ocr_job(request, timeout_seconds=120)   # 默认 120 秒
```

`dpi`、`max_ram_bytes` 由 `OCRRegionRequest` 传入，调用方决定；`scripts/ocr_demo.py` 使用 `dpi=220`、`max_ram_bytes=8 GiB`。

### 8.2 `ResourcePolicy`

文件：`tools/resource_limits.py`

| 字段 | 默认值 |
|---|---:|
| `soft_ram_bytes` | 2 GiB |
| `hard_ram_bytes` | 3 GiB |
| `batch_pages` | 1 |
| `working_dpi` | 300 |
| `final_asset_dpi` | 300 |
| `soft_vram_bytes` | 6 GiB |

`ResourcePolicy.from_system()`：soft RAM = 物理内存 25% 且 ≤ 8 GiB；hard RAM = 物理内存 35% 且 ≤ 10 GiB；物理内存 < 16 GiB 时 `batch_pages=1`，否则 2。

`after_oom(batch_pages, working_dpi)`：OOM 后退避——批量降为 1，工作 DPI 降到 220（或每次减 40、不低于 150），最终资源 DPI 不变。

---

## 9. 错误码与排错

| 错误 | 触发位置 | 含义 | 处理方式 |
|---|---|---|---|
| `unsupported_engine:<name>` | `_worker()` | `engine` 不在 `fake/production/rapidocr`。 | 修正 `OCRRegionRequest.engine`。 |
| `model_missing:rapidocr` | `_run_rapidocr()` | 适配器目录不存在或 RapidOCR 依赖 import 失败。 | 恢复生产适配器，或测试时用 `fake`；检查 `LITWISE_RAPIDOCR_ADAPTER`。 |
| `rapidocr_failed:<message>` | `_run_rapidocr()` | PDF 打开、渲染或模型调用异常。 | 检查 PDF 路径/页码/区域坐标、适配器与依赖。 |
| `timeout` | `run_ocr_job()` | worker 超过 `timeout_seconds`。 | 减少区域面积、降低工作 DPI、提高 timeout。 |
| `resource_limit_exceeded` | `run_ocr_job()` | worker 峰值 RSS 超过 `max_ram_bytes`。 | 单区域重试、降低 DPI，参考 `ResourcePolicy.after_oom()`。 |

推荐排查顺序：

1. 用 `scripts/ocr_demo.py` 逐页诊断，看状态分布与 `repair_regions`。
2. 用 `engine="fake"` 验证问题是否在 worker 协议本身，而非模型。
3. 检查 `models/production/rapidocr-adapter` 是否存在且含 `rapidocr` 包目录。
4. 检查 `OCRRegionRequest` 的 `pdf_path`、`page`、`regions` 是否有效。
5. 直接调用 `extract_page_signals()` + `diagnose_page()` 查看触发原因。

---

## 10. 测试与验证

```powershell
# 全部（10 个）
python -m pytest tests/

# 单独
python -m pytest tests/test_ocr_worker.py        # fake worker 协议 / 未知 engine / 适配器缺失
python -m pytest tests/test_page_diagnostics.py  # native_pass / ocr_required / manual_review 决策
python -m pytest tests/test_resource_limits.py   # from_system / after_oom 资源策略
```

真实模型验证：

```bash
python scripts/ocr_demo.py "E:\papers\scan.pdf"          # 全文诊断
python scripts/ocr_demo.py "E:\papers\scan.pdf" 1 2 3    # 对指定页跑真实 RapidOCR
```

---

## 11. 当前已知限制

1. 只有一套完成实测的 RapidOCR 适配器，尚未形成第二模型一致性验证。
2. 单模型置信度上限 0.94，低置信度结果默认需要人工复核（本工具集只给出 `manual_review` 状态，不负责准入）。
3. 复杂表格、公式和旧式中文扫描 PDF 可能无法自动恢复，落入 `manual_review`。
4. `character_confidences` 对 RapidOCR 为空，不能当作逐字符质量证明。
5. `language` 字段进入请求契约，但 RapidOCR 适配器没有据此切换多语言模型。
6. RapidOCR 对英文可能丢空格（如 `Magnetismin`），OCR 结果需人工抽查。
7. 本工具集不重排文本、不合并表格、不做 PDF→Markdown；这些能力在 `pdf2md/`。

---

## 12. 维护约定

修改 OCR 流程时至少同步检查：

1. `ocr_contracts.py` 字段是否与 `ocr_worker.py --worker` 的 JSON 协议一致。
2. `page_diagnostics.py` 阈值变化是否更新对应单元测试与本文档 §3。
3. `ocr_worker.py` 的引擎名、退出码、错误串是否与本文档 §5/§9 一致。
4. 新增模型在隔离环境评估，记录模型版本、大小、哈希、峰值 RSS、耗时与失败页面。
5. 模型权重与运行时产物加入 `.gitignore`，不提交到仓库。

本文档只描述当前实现状态，不把未接入的 ensemble OCR、表格结构化、公式识别或第二模型复核写成已存在能力。
