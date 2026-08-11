# PDF → Markdown 零 token 独立工具 · 实现计划

> 历史实现计划：其中关于首次运行下载模型的描述已失效。当前安装与离线转换契约以
> `docs/superpowers/specs/2026-08-11-release-model-distribution-design.md` 和
> `models/models.lock.json` 为准。

> 版本：v1（2026-08-08）
> 状态：待批准
> 目标：不消耗任何 LLM token，把 PDF 转成**规范化的 Markdown**，供后续任意 AI 直接消费。
> 依据：三个既有项目的源码、文档、真实测试输出；已确认本机已安装的依赖。

---

## 0. 定位

这是一个**独立命令行工具**（命名 `pdf2md`），落在 `litwise-ocr` 目录下的子目录（已确认决策）：

```text
E:\Codex\yunshu-OCR\pdf2md\
```

与 `tools/`（OCR 修复）职责平行：`tools/` 管 OCR 修复，`pdf2md/` 管 PDF→Markdown 转换。

复用资产（跨项目拷贝或按路径引用，不重写）：

| 来源 | 复用物 |
|---|---|
| `yunshu-litwise/tools/layout_converter.py` | 四层管线骨架：doclayout_yolo 版面 → PyMuPDF 抽字/图片 → 分类 → 排序组装 |
| `litwise-unified/tools/reading_order.py` | `order_page_elements()` 列排序、`classify_repeated_margins()` 页眉页脚识别、`group_semantic_elements()` 图文分组 |
| `litwise-ocr` | RapidOCR 适配器 + `page_diagnostics.py`（OCR 兜底）、`resource_limits.py` |
| 本机 pip | `doclayout_yolo`、`PyMuPDF`、`texify`、`opendataloader-pdf`、`torch`(CPU)、`onnxruntime` |

**明确不用 MinerU / marker**：未安装；marker 公式最强的 balanced 模式必须 GPU（本机无 GPU）；MinerU 模型 ~6.3GB 且较重。它们作为**可选升级链**写入文档，不阻塞主链。

---

## 1. 目标输出格式（转换器必须满足的契约）

一个 PDF 产出：

```text
<output>/
├── <book>.md                  # 唯一最终产物，AI 直接吃这个
├── images/                    # 图片单独存放，MD 用相对链接引用
│   ├── page3_figure_01.png
│   └── ...
└── layout.json                # 侧车：逐页元素 + bbox + 类型 + 页眉页脚标记（溯源用）
```

`<book>.md` 的规范（示例）：

```markdown
> **元数据块**
> - 标题：Magnetism in Condensed Matter
> - 作者：Stephen Blundell
> - 年份 / 来源：2023 / Oxford Master Series
>
> 来源：第 1 页结构化抽取（标题/作者/机构/摘要/关键词）

## Page 1

正文段落…

一些行内公式 $E = h\nu$ 与块级公式：

```latex
\frac{\mathrm{d}\boldsymbol{B}}{\mathrm{d}t}
```

| $T$ (K) | $\chi$ (emu/mol) |
|---------|-----------------|
| 5.0     | 0.012           |
| 300.0   | 0.0001          |

![Figure 1.1](images/page3_figure_01.png)

*Figure 1.1  Caption text…*

## Page 2

<!-- header -->
Running Title / Journal Name / 页码号
<!-- /header -->

下一页正文内容…

<!-- footer -->
Page 42 of 210
<!-- /footer -->
```

**规则表**：

| 内容 | 表示 | 说明 |
|---|---|---|
| 分页 | `## Page N` 标题 | 人类可读、渲染可见，AI 能直接定位页码 |
| 元数据 | 顶部 `> 元数据块` 结构化 | 标题/作者/年份/来源/摘要/关键词 |
| 正文 | 普通段落 | 换行拼接，不丢字 |
| 块级公式 | ` ```latex … ``` ` 代码块 | 用户明确要求"代码形式储存" |
| 行内公式 | `$…$` | texify 或符号直出 |
| 表格 | 标准 Markdown 表格 | 含表头；复杂表降级为图片+链接并记入 layout.json |
| 图片 | `![caption](images/xxx.png)` | 图片实体提取到 `images/`，MD 引用相对路径 |
| 页眉/页脚 | **默认标注保留**：`<!-- header -->…<!-- /header -->`、`<!-- footer -->…<!-- /footer -->` 包裹 | "精准区分" = 内容不丢、且不混入正文 |

---

## 2. 引擎选型（本机实测可用）

| 环节 | 引擎 | 依据 |
|---|---|---|
| 版面检测 | `doclayout_yolo`（已装 0.0.2b1） | 输出 text/title/figure/table/formula/list 视觉块 |
| 文字提取 | PyMuPDF `page.get_text("rawdict")`（已装 1.24.14） | 原生无损；保留字体/字号/bbox 供公式与页眉页脚判断 |
| 图片提取 | PyMuPDF `page.get_pixmap(clip=…)` | 已有代码可复用 |
| **表格→MD** | **PyMuPDF `page.find_tables()`**（内置，CPU，无需模型） | 有框表格效果良好；合并单元格降级为图片 |
| **公式→LaTeX** | **`texify` 0.2.1（已装）** | 检测到 formula 块 → crop → texify → ` ```latex ` |
| 文字缺失 OCR 兜底 | RapidOCR（vendored，onnxruntime CPU） | 复用 litwise-ocr worker |
| 快速纯文本备选 | `opendataloader-pdf`（已装 2.4.7） | 失败/超时时的确定性兜底 |

> ⚠️ texify 首次运行需从 HF 下载权重（约数百 MB，一次性，不算 token 消耗）。yunshu 曾记录 HF 网络不通——**这是首要验证项（P0）**，见 §7。

---

## 3. 架构与模块

```text
litwise-ocr/pdf2md/
├── requirements.txt
├── pdf2md/
│   ├── cli.py            # 命令行入口 + 参数解析
│   ├── pipeline.py       # 主编排：引擎 → 修复 → 排序 → 规范 → 验证
│   ├── layout.py         # doclayout_yolo 版面检测（拷贝自 layout_converter Phase1）
│   ├── text.py           # PyMuPDF 文字/图片提取（拷贝自 layout_converter Phase2）
│   ├── classify.py       # 内容分类（拷贝自 layout_converter Phase3）
│   ├── order.py          # 阅读顺序 + 页眉页脚（复用 reading_order.py 逻辑）
│   ├── tables.py         # find_tables() → MD 表格；复杂表降级
│   ├── formulas.py       # texify 接入 → 公式代码块
│   ├── normalize.py      # 【新】输出规范后处理：分页标题/公式代码块/图片相对路径
│   ├── textloss.py       # 【新】文字不丢失验证门禁
│   ├── ocr.py            # RapidOCR 兜底（复用 tools/ 的 worker）
│   └── sidecar.py        # layout.json 写出
├── tests/
│   ├── test_tables.py
│   ├── test_formulas.py
│   ├── test_normalize.py
│   └── test_textloss.py
└── README.md
```

---

## 4. 分阶段实施（每阶段有独立可验收输出）

### Phase 0 — 脚手架与验证（0.5 天）
- [ ] 建 `pdf2md/` 目录、`requirements.txt`、`pyproject.toml`（或简单 requirements）。
- [ ] **P0 验证：texify 权重能否下载、能否在本机 CPU 跑通一个公式**。失败则立即降级方案（§7）。
- [ ] 验证 `doclayout_yolo` 模型路径存在、`page.find_tables()` 在测试 PDF 上可用。

### Phase 1 — 版面+文字+图片（1 天，产出 v0）
- [ ] 拷贝 layout_converter Phase1/2/3，**删除 TABLE→存图 分支**（这是对用户需求的直接违反）。
- [ ] 分页标记统一为 `## Page N` 标题（Phase 5 normalize 里保证）。
- [ ] 图片提取规则不变（面积 >2% 页面的 figure 才保存）。
- [ ] 验收：测试 PDF 出 v0 markdown，正文不丢、图片已链接、分页注释每页一个。

### Phase 2 — 表格→MD（1 天）
- [ ] `tables.py`：对 YOLO 标为 table 的区域跑 `page.find_tables()`，输出 MD 表格。
- [ ] `find_tables()` 无结果或结构可疑（合并单元格多）→ 降级为图片 + `layout.json` 记 `table_as_image:true`。
- [ ] 跨页表格：暂记 `layout.json` 的 `table_continues:true`（v1 不合并，v2 处理）。
- [ ] 验收：`曲波涛…锌配位聚合物.pdf` 的实验数据表还原为可读 MD 表格。

### Phase 3 — 公式→LaTeX（1–1.5 天，最难）
- [ ] `formulas.py`：从 YOLO `formula` 类块 + 字体启发式（斜体数学字体、Unicode 数学符号）找公式区域。
- [ ] crop 区域 → `texify` → LaTeX。
- [ ] 块级公式包裹 ` ```latex ``` `；行内 `$…$`。
- [ ] texify 失败/低置信 → 保留原 Unicode 符号文本，`layout.json` 记 `formula_uncertain:true`。
- [ ] 验收：在 Blundell 课本与配位聚合物论文上，抽 20 个公式人工核对，目标 ≥70% 可读 LaTeX。

### Phase 4 — 阅读顺序 + 页眉页脚（1 天）
- [ ] 移植 `order_page_elements()`：宽元素优先 → 左右栏各自纵排。
- [ ] 移植 `classify_repeated_margins()`：跨页重复的顶部/底部文本 → `header`/`footer`。
- [ ] **默认标注保留**：`<!-- header -->…<!-- /header -->`、`<!-- footer -->…<!-- /footer -->` 包裹，不混入正文。
- [ ] 验收：Blundell 书双栏页阅读顺序正确；页眉（书名/章节名）不再混入正文。

### Phase 5 — 输出规范后处理（0.5 天）
- [ ] `normalize.py` 一次性保证契约：分页注释、公式代码块、表格、图片相对路径、空行规整。
- [ ] 验收：任意中间产物过 normalize 后都符合 §1 契约，可用 lint 测试断言。

### Phase 6 — 文字不丢失验证门禁（0.5 天）
- [ ] `textloss.py`：逐页比对「PDF 原生文本字符数」vs「输出 MD 本页字符数」，算覆盖率。
- [ ] 覆盖率 < 阈值（如 95%）→ 该页进 `layout.json` 的 `text_loss` 列表；整文在退出码与摘要中报告。
- [ ] 复用 `page_diagnostics` 的损坏信号（替换字符/控制字符）识别需要 OCR 的页。
- [ ] 验收：v1 工具在 Blundell 25 页切片上，**覆盖率 ≥ 98% 且逐页给出报告**。

### Phase 7 — OCR 兜底（0.5 天）
- [ ] 损坏页（低原生保留/乱码）自动路由到 RapidOCR worker，OCR 文本以 `<!-- ocr:page N -->` 标注并入页。
- [ ] 验收：Blundell 扫描封面/插图页能从 0 字恢复到可读文本（已知 RapidOCR 会丢英文空格——v1 接受、记 manual_review，v2 考虑后处理补空格）。

### Phase 8 — CLI + 端到端验收（0.5 天）
- [ ] `pdf2md <in.pdf> --output <dir> [--drop-margins] [--lang zh|en] [--no-ocr] [--max-dpi 220]`
- [ ] 端到端跑两个语料（英文物理书切片、中文化学论文），对照 §5 验收指标出报告。

---

## 5. 验收指标（可量化，跑真实语料）

| 指标 | 目标 |
|---|---|
| 原生数字 PDF 字符覆盖率 | ≥ 98%（逐页） |
| 分页注释数量 | = PDF 页数 |
| 图片提取 + 链接 | 100% figure 块链接有效（相对路径存在） |
| 表格还原 | 简单表 100% 为 MD 表格；复杂表降级并记档 |
| 公式 LaTeX | 抽查 20 个公式 ≥ 70% 可读（无 GPU 现实目标） |
| 页眉页脚 | 标注保留且不混入正文；页眉/页脚计数与跨页重复匹配数一致 |
| 零 token | 全链路无 LLM 调用（断言：无 API key、无网络请求） |
| 速度 | 中文 8 页 ≤ 15s；英文 15 页 ≤ 20s（doclayout_yolo 是主耗时） |

---

## 6. 风险与降级预案

| 风险 | 概率 | 预案 |
|---|---|---|
| texify 权重下载失败（HF 不通） | 中 | 用 `pix2tex`/已有 ONNX 公式模型；或 v1 公式先以 Unicode+` \[…\] ` 标记，标注"待公式化" |
| 无 GPU 公式准确率不理想 | 高 | 现实目标是"可读"而非"完美"；把不确定公式显式标记，供人工/AI 后处理 |
| 复杂合并单元格表格 | 中 | 降级为图片，不硬造 MD 表格 |
| 跨页表格 | 高 | v1 记 `table_continues`，v2 做跨页合并 |
| 扫描页 OCR 英文空格丢失 | 高（已实测） | v1 接受 + manual_review 标记；v2 做空格还原后处理 |
| 双栏段落级顺序偏差 | 中 | 用 `order_page_elements` 替代简单 x_center 二分；验收页抽查 |

---

## 7. 依赖清单（需新增安装）

| 包 | 状态 | 用途 |
|---|---|---|
| `texify` | 已装 0.2.1 | 公式→LaTeX（权重需首跑下载） |
| `doclayout_yolo` | 已装 | 版面检测（权重已在本地缓存） |
| `PyMuPDF` | 已装 | 文字/图片/表格 |
| `opendataloader-pdf` | 已装 | 快速兜底 |
| RapidOCR（vendored） | 已装 | OCR 兜底 |
| （可选）`magic-pdf` / `marker-pdf` | 未装 | 后续升级链（marker balanced 需 GPU） |

不需要新增网络请求、API key；转换全链路离线。

---

## 8.5 实现完成 · 实测结果（2026-08-08）

工具已完成并在两个真实语料上跑通：

| 验收项 | Blundell 前25页 (英文物理书) | 曲波涛论文 (中文化学) |
|---|---|---|
| 耗时 | 57s / 25页 | 17s / 8页 |
| 文字不丢失 (逐页 MD≥原生) | 25/25 OK | 8/8 OK |
| 元数据 (标题/年份/作者) | ✓ | 标题/年份 ✓ |
| 公式 → ` ```latex ` | 27 (11 不确定) | 2 |
| 表格 | 有框表→MD, 图片表→图片 | 图片表→图片 |
| 页眉页脚 | "N Introduction" 6页已标注 | — |
| 假表格 (散文误判) | 0 | 0 |
| 假公式 (图注误判) | 0 | 0 |

关键实现决策（与 §5 初版相比的演进）：
- **公式**：texify 权重 HF 不可达 → 实装"空隙检测器"（文字块之间有墨迹但无文字的区域 → OCR → 符号映射），成功恢复文字层不可见的显示公式。
- **表格**：find_tables 默认策略对无框/细线表无效 → 按"区域原生文字行长度"判别表格数据 vs 散文，text 策略只在真表格数据上用，消除双栏散文假表格。
- **页眉页脚**：改为直接读文字层找跨页重复文本（YOLO 区域文字跨页不一致），页眉钉页首、页脚钉页尾。
- **假公式守卫**：OCR 结果无数学符号 → 降为正文（YOLO 把图注/标题误判为 formula）。

单元测试 19 个全部通过（`python -m pytest pdf2md/tests/`）。

## 8.6 修复轮 (2026-08-08, 用户实测反馈)

用户实测反馈两类问题，已修复并加 lint 反馈环（`pdf2md/lint.py`，对已知失败模式亮红）：

| 用户报告 | 根因 | 修复 | lint 前后 |
|---|---|---|---|
| 标题错乱给错级别 | ① 目录页条目/合并块被当标题（带页码、多条目录一行）② 中文段落 `word_count` 恒为 1，正文含关键词误判 H2 | classify: TOC 块检测（多节号/结尾页码→正文）+ 标题守卫改 `char_count≤40` | Blundell 58→1，化学 LINT OK |
| 公式错译/遗漏/错位 | 空隙带含多条堆叠公式整体 OCR 合并；截断；矩阵 OCR 固有局限 | 空隙按墨迹行拆分（`split_ink_lines`），每条公式单独 OCR | 合并公式已拆开 |

新增回归测试：中文正文不判 H2、TOC 合并/条目不判标题、真实标题仍正确、公式行拆分。残留已知项：矩阵/自旋量公式 RapidOCR 仍会乱码（无公式模型，如实记录，lint 标记 + layout.json 记 uncertain）。

## 8.7 公式引擎升级 (2026-08-08)

用户反馈公式转译效果差。根因：RapidOCR 是文字 OCR，不识数学结构。升级路径：

- 尝试 texify 0.2.1 → 权重可下载但 **与新版 transformers 不兼容**（`AttributeError: 'dict' object has no attribute 'to_dict'`）。
- 改用 **pix2tex (LaTeX-OCR)**（更活跃维护、~90M、兼容现代 transformers）。`pip install pix2tex`，权重首跑从 HF 下载。
- 接入：`formulas.py::FormulaModel`（懒加载 + 失败回退 RapidOCR），`ocr_formula_latex` 一次渲染共用，返回 `(latex, conf, engine)`。
- CLI 加 `--formula-engine auto|pix2tex|rapidocr`。

质量对比（Blundell 书, RapidOCR→pix2tex）：
- `B = \muo(1+x)H = \muo\murH` → `\mathbf{B}=\mu_{0}(1+\chi)\mathbf{H}=\mu_{0}\mu_{\mathrm{r}}\mathbf{H}`（χ/下标全对）
- `dv aA =-qv-q + qv x (V x A)` → `m\frac{\mathrm{d}\mathbf{v}}{\mathrm{d}t}=-q\nabla V-q\frac{\partial\mathbf{A}}{...}`（分数/∇/偏导对）
- 矩阵 `a3 a1 102 a` → `\sigma\cdot{\bf a}=\begin{pmatrix}a_3&a_1-ia_2\\...\end{pmatrix}`（矩阵重建）

新假阳性守卫：`\mathrm{prose}` 不算公式、超大数组(>12列)不算公式、间距垫白(`\qquad/\quad/~`)塌缩。残留：等式编号偶读成 `\mathbf{Q.NN}`、`v/y/ν` 偶混。

## 8. 已确认决策（2026-08-08）

| 决策点 | 选择 |
|---|---|
| 目录 | `litwise-ocr/pdf2md/` 子目录（与 `tools/` OCR 职责平行） |
| 页眉页脚 | **默认标注保留**：`<!-- header -->…<!-- /header -->` 包裹，不混入正文 |
| 分页标记 | `## Page N` 标题 |
| 元数据块 | 顶部 `> 元数据块` 结构化输出（标题/作者/年份/来源/摘要/关键词） |
