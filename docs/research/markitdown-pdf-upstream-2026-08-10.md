# Microsoft MarkItDown PDF→Markdown 上游能力核查

> 核查日期：2026-08-10（Asia/Shanghai）
> 核查对象：[microsoft/markitdown](https://github.com/microsoft/markitdown)
> 固定版本：正式版 [`v0.1.7`](https://github.com/microsoft/markitdown/releases/tag/v0.1.7)，对应提交 [`fd239d5d2be43d9b68329730206b9312c7d5a388`](https://github.com/microsoft/markitdown/commit/fd239d5d2be43d9b68329730206b9312c7d5a388)（2026-07-29）
> 资料边界：官方 README、源码、`pyproject.toml`、官方测试、GitHub Releases；不采用第三方测评推断能力。

## 1. 结论先行

MarkItDown 的“PDF 转 Markdown”不能作为一个单一能力评价，必须拆成三条路径：

1. **内置 PDF 转换器（默认本地路径）**：轻量、离线、输入接口广，适合带文本层 PDF 的纯文本抽取，以及发票、表单、边框缺失表格等规则性材料。它不做 OCR，不输出公式语义，不保留页码、块坐标、置信度或来源映射，对科研论文多栏版面也没有专门阅读顺序模型。
2. **`markitdown-ocr` 独立插件**：需要显式安装、启用插件，并由用户提供兼容 OpenAI API 的视觉模型。它可识别 PDF 内嵌图像，并为纯扫描 PDF 提供整页视觉 OCR 兜底，但输出仍主要是 Markdown 文本，没有可消费的坐标、置信度和结构化失败状态；真实 OCR 准确率不由现有测试证明。
3. **Azure Document Intelligence / Content Understanding**：官方明确定位为更高质量的云端版面分析和 OCR，适合扫描件、复杂表格和多页文档，但属于 Azure 依赖和计费 API，不能算作默认本地开源转换器的能力。

因此，若比较目标是“通用文件快速转为适合 LLM 消费的 Markdown”，MarkItDown 很有竞争力；若比较目标是“科研 PDF 的可追溯、高保真、可人工复核文档理解”，其默认本地 PDF 路径明显不是同一深度的产品定位。官方 README 自己也说明：它是面向 LLM/文本分析的轻量工具，不一定适合人类阅读所需的高保真转换（[`README.md` L7-L10](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L7-L10)）。

## 2. 架构与转换流程

### 2.1 内置 PDF 转换器

入口类是 `packages/markitdown/src/markitdown/converters/_pdf_converter.py::PdfConverter`。接受 `.pdf`、`application/pdf` 和 `application/x-pdf`（[`_pdf_converter.py` L495-L518](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L495-L518)）。

实际处理流程如下：

- 将输入流一次性读入 `BytesIO`（[`_pdf_converter.py` L537-L540](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L537-L540)）。
- 用 `pdfplumber` 逐页取词和坐标，启发式判断页面是否像表单/表格；命中的页面生成 Markdown 表格或文本，普通页使用 `page.extract_text()`（[`_pdf_converter.py` L542-L566](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L542-L566)）。
- 如果整份文档没有任何“表单型页面”，重新用 `pdfminer.high_level.extract_text()` 抽整份文档；`pdfplumber` 失败也回退到 `pdfminer`（[`_pdf_converter.py` L568-L584](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L568-L584)）。
- 最后只做一项特定后处理：把 MasterFormat 风格的 `.1`、`.2` 等部分编号与下一文本行合并（[`_pdf_converter.py` L10-L57](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L10-L57)、[`L586-L589`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L586-L589)）。

内存方面，v0.1.6 加入了逐页 `page.close()`，避免 `pdfplumber` 页面缓存随页数线性增长；源码也明确注释这一目的（[`_pdf_converter.py` L543-L566](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L543-L566)，[v0.1.6 release](https://github.com/microsoft/markitdown/releases/tag/v0.1.6)）。但输入 PDF 本身仍被整体读入内存，不能视为真正的流式 PDF 解析。

### 2.2 表格/表单启发式

内置转换器并非简单调用 `pdfminer`：它有一套基于词的 `x0/x1/top` 坐标、行聚类、列起点聚类、列密度和长单元格比例的规则，用来识别无边框表单和表格（[`_pdf_converter.py` L120-L299](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L120-L299)）。输出会生成带表头分隔行的 Markdown 表格（[`_pdf_converter.py` L301-L395](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L301-L395)）。

这一能力的边界也写在源码中：单独的词坐标表格提取器面向发票等结构化表格，**不是为科研文档的多栏正文布局设计**（[`_pdf_converter.py` L398-L405](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L398-L405)）。

### 2.3 OCR 插件的替换机制

`markitdown-ocr` 是仓库内的**独立 Python 包和插件**，不是内置 `[pdf]` 转换器自动开启的能力。插件通过 `markitdown.plugin` entry point 注册（[`markitdown-ocr/pyproject.toml` L52-L57](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/pyproject.toml#L52-L57)），以 `-1.0` 优先级把 OCR 增强版 PDF/DOCX/PPTX/XLSX 转换器排在内置转换器之前（[`_plugin.py` L19-L67](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_plugin.py#L19-L67)）。

插件默认仍不执行 OCR：必须同时满足安装插件、`enable_plugins=True`/`--use-plugins`、提供 `llm_client` 和 `llm_model`。否则 OCR service 为 `None`（[`_plugin.py` L35-L47](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_plugin.py#L35-L47)），README 表述为“静默跳过 OCR，回退标准转换”（[`README.md` L130-L160](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L130-L160)）。

## 3. PDF 解析依赖与部署边界

### 3.1 内置本地 PDF

- Python：`>=3.10`，包状态 classifier 为 Beta（[`packages/markitdown/pyproject.toml` L5-L24](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/pyproject.toml#L5-L24)）。
- PDF extra：`pdfminer.six>=20251230`、`pdfplumber>=0.11.9`（[`pyproject.toml` L35-L57](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/pyproject.toml#L35-L57)）。
- 安装：可装 `[all]`，也可只装 `[pdf]`；官方列出了格式级 optional dependencies（[`README.md` L61-L69](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L61-L69)、[`L91-L112`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L91-L112)）。
- Docker：仓库给出官方构建和 stdin→stdout 示例（[`README.md` L283-L288](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L283-L288)）。

内置 PDF 路径不需要外部模型、GPU 或网络调用，适合嵌入 Python 服务、批处理或 CLI。

### 3.2 OCR 插件

插件依赖包括 `pdfminer.six`、`pdfplumber`、`PyMuPDF`、Pillow，并因同一插件覆盖 Office 格式而带入 Mammoth、python-docx、python-pptx、pandas、openpyxl 等（[`markitdown-ocr/pyproject.toml` L26-L38](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/pyproject.toml#L26-L38)）。OpenAI SDK 本身是可选 extra，因为插件接受用户传入的 OpenAI-compatible client（[`L40-L45`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/pyproject.toml#L40-L45)）。

所以它不是传统的本地 OCR 引擎：默认实现会把图片编码成 base64 data URI，调用 `client.chat.completions.create()` 的视觉模型（[`_ocr_service.py` L63-L106](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_ocr_service.py#L63-L106)）。是否本地、是否离线、成本、数据出境边界取决于用户接入的兼容客户端和模型服务。

### 3.3 Azure 路径

`[az-doc-intel]` 和 `[az-content-understanding]` 是另外的 optional dependencies（[`pyproject.toml` L49-L63](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/pyproject.toml#L49-L63)）。官方把 Content Understanding 定位为针对扫描 PDF、复杂表格、多页文档的更高质量云端版面/OCR，并明确每次命中 CU 的 `convert()` 是可计费 Azure API 调用（[`README.md` L162-L183](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L162-L183)、[`L224-L235`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L224-L235)）。Document Intelligence 的 CLI/API 使用也需 Azure endpoint（[`README.md` L239-L268](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L239-L268)）。

## 4. 扫描 PDF 与 OCR

### 4.1 内置转换器：明确不支持扫描件 OCR

内置 `_pdf_converter.py` 只导入 `pdfminer` 和 `pdfplumber`，处理路径只有文本/词坐标抽取，没有图像渲染或 OCR 调用（[`_pdf_converter.py` L60-L67](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L60-L67)、[`L520-L589`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L520-L589)）。官方测试甚至明确断言：无文本层的医疗扫描 PDF 应输出空字符串（[`test_pdf_tables.py` L951-L978](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L951-L978)）。

### 4.2 OCR 插件：视觉模型识别嵌图与扫描页

插件有两种 OCR 路径：

- **内嵌图片路径**：从 `page.images`、底层对象或 XObject 中找图片；能直接解码图片流时转成 PNG，否则按图片 bbox 裁剪页面并以 150 DPI 渲染（[`_pdf_converter_with_ocr.py` L28-L126](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L28-L126)）。图片 OCR 文本和页面文本按纵向 `y` 排序后插入（[`L186-L290`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L186-L290)）。
- **整页扫描兜底**：把页面以 300 DPI 渲染，再交给视觉模型；若 `pdfplumber` 无法打开，还会用 PyMuPDF 渲染（[`L340-L420`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L340-L420)）。

需要注意一处 README 与实现粒度的差异。插件 README 称“无可提取文本的页面会被自动检测，并逐页以 300 DPI 发送给 LLM”（[`markitdown-ocr/README.md` L103-L110](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/README.md#L103-L110)）。但源码循环中没有一个显式的“当前页无文本 → 当前页整页 300 DPI OCR”分支；300 DPI `_ocr_full_pages()` 是在**最终整份 Markdown 为空**时才触发（[`_pdf_converter_with_ocr.py` L289-L311](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L289-L311)）。

普通扫描页常会因整页栅格被识别为内嵌图片而进入第一条 OCR 路径；真正的风险是：混合了文本页和扫描页、扫描栅格未被 `_extract_page_images()` 检出，或页面标题/少量文本使最终结果不再为空时，文档级 300 DPI 兜底可能不触发。这一点应通过真实混合 PDF 单独验证，不能只依据 README 宣传语。

## 5. 表格、公式、多栏与图像理解

### 5.1 表格

内置转换器对规则性表格是实质能力，而非仅保留空格：

- 生成 Markdown pipe 表格和 header separator（[`_pdf_converter.py` L78-L117](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L78-L117)）。
- 官方测试验证无边框表格包含 pipe 行、产品代码与多列结构（[`test_pdf_tables.py` L989-L1037](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L989-L1037)）。
- 还验证多页发票存在十余行表格和多列数据（[`test_pdf_tables.py` L1048-L1093](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L1048-L1093)）。

局限在于它依赖固定阈值和统计启发式；跨页合并单元格、复杂嵌套表格、科研论文表格标题/脚注绑定，不在其输出 contract 或现有测试保证范围内。

### 5.2 公式

固定版本的 PDF 转换器中没有公式检测、数学区域分类、MathML/LaTeX 恢复或公式图像 OCR 分支；它只抽文本和表格。仓库在 DOCX 转换中存在 OMML/LaTeX 相关代码，但不能据此推导 PDF 公式能力。`v0.1.7` 发布说明中的公式修复也针对 equation conversion/OMML，不是 PDF 公式解析（[v0.1.7 release](https://github.com/microsoft/markitdown/releases/tag/v0.1.7)）。

使用 OCR 插件时，公式图片会被当成普通图像交给视觉模型；默认 prompt 仅要求“提取全部文本、保持原布局和顺序”，没有指定 LaTeX 或公式语法（[`_ocr_service.py` L42-L46](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_ocr_service.py#L42-L46)）。因此公式质量取决于模型和自定义 prompt，不能视为稳定的 PDF 公式转写模块。

### 5.3 多栏和阅读顺序

内置 PDF 逻辑没有专门的版面模型或栏检测；普通文档主要依赖 `pdfminer`/`pdfplumber` 的文本顺序。源码还明确说表格辅助算法并不用于科研文档多栏正文（[`_pdf_converter.py` L398-L405](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L398-L405)）。

OCR 插件在含图片页面上将字符按 `(top, x0)` 排序分行，再把文本行和图片仅按 `y_pos` 排序（[`_pdf_converter_with_ocr.py` L196-L277](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L196-L277)）。这种“从上到下、同行从左到右”的规则不等价于多栏阅读顺序恢复，双栏论文可能出现左右栏交错。

### 5.4 图片描述与 LLM

MarkItDown 内置的 `llm_client` 图片描述能力，官方限定为 PPTX 和独立图片文件，不包括内置 PDF 转换器（[`README.md` L271-L280](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L271-L280)）。PDF 内图片需通过 `markitdown-ocr` 插件才会发给视觉模型，且默认目标是 OCR 文本，不是语义图注、图表数据重建或图像描述。

## 6. 元数据、页码、坐标与置信度

### 6.1 内置输出 contract

`DocumentConverterResult` 只有：

- 必填 `markdown: str`
- 可选 `title: str`

源码没有 blocks、pages、bbox、confidence、source map 或 warnings 字段（[`_base_converter.py` L5-L39](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/_base_converter.py#L5-L39)）。内置 `PdfConverter` 最终只返回 `DocumentConverterResult(markdown=markdown)`，没有 title 或 PDF 元数据（[`_pdf_converter.py` L586-L589](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/converters/_pdf_converter.py#L586-L589)）。

内置表格识别内部确实使用坐标，但这些坐标只用于生成最终 Markdown，未作为结果返回。内置结果也不插入页分隔，因此 Markdown 不能可靠回指原 PDF 页码。

### 6.2 OCR 插件输出

OCR 插件会在 Markdown 中添加 `## Page N` 和 `*[Image OCR] ... [End OCR]*` 标记（[`_pdf_converter_with_ocr.py` L186-L190](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L186-L190)、[`L268-L277`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py#L268-L277)），因此比内置转换器多了粗粒度页号和 OCR 来源标识。

`OCRResult` 数据类声明了 `confidence`、`backend_used` 和 `error`（[`_ocr_service.py` L13-L20](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_ocr_service.py#L13-L20)），但默认 LLM service 成功时只写 `text` 和 `backend_used`，未设置 confidence（[`L102-L108`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/src/markitdown_ocr/_ocr_service.py#L102-L108)）。转换器也只把 OCR 文本拼入 Markdown；内部 `y_pos`、图片 bbox、backend、error、confidence 均不进入最终 `DocumentConverterResult`。因此它没有可供人工复核或知识库引用的块级坐标/置信度 contract。

## 7. 输入输出与安全边界

Python API 的 `convert()` 可接收：

- 本地路径字符串或 `Path`
- `http:` / `https:` / `file:` / `data:` URI
- `requests.Response`
- 二进制流

详见 [`_markitdown.py` L275-L323](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/_markitdown.py#L275-L323) 和 URI 路由 [`L428-L487`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/_markitdown.py#L428-L487)。不可 seek 的流会先完整缓冲到 `BytesIO`（[`L362-L407`](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/src/markitdown/_markitdown.py#L362-L407)）。

CLI 支持本地文件输出到 stdout、`-o` 文件，以及 stdin 管道（[`README.md` L71-L89](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L71-L89)）。这一点非常适合 Unix 管道、脚本和服务集成。

但通用 `convert()` 也扩大了安全边界。官方警告它会以当前进程权限访问文件系统和网络，服务端应验证不可信输入，并优先调用更窄的 `convert_local()`、`convert_stream()` 或自主管理请求（[`README.md` L342-L348](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/README.md#L342-L348)）。

## 8. 测试能证明什么，不能证明什么

### 已有证据

- 内置转换器测试验证学术 PDF 能抽出关键章节/词语，并确保没有误生表格 pipe；但没有验证公式、双栏顺序或坐标保真（[`test_pdf_tables.py` L910-L949](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L910-L949)）。
- 表格测试覆盖无边框表格、多页发票、多列 pipe 结构和关键数据存在性（[`test_pdf_tables.py` L989-L1093](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L989-L1093)）。
- 内置扫描件测试明确证明默认路径返回空，不会自行 OCR（[`test_pdf_tables.py` L951-L978](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/tests/test_pdf_tables.py#L951-L978)）。
- OCR 插件测试覆盖图片位于页首/中/尾、多图片、复杂布局、纯扫描件和损坏 PDF 的 PyMuPDF 兜底（[`markitdown-ocr/tests/test_pdf_converter.py` L61-L189](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/tests/test_pdf_converter.py#L61-L189)）。

### 不能据此声称的能力

OCR 插件测试使用 `MockOCRService`，对所有图片固定返回 `MOCK_OCR_TEXT_12345`（[`test_pdf_converter.py` L1-L58](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown-ocr/tests/test_pdf_converter.py#L1-L58)）。这些测试证明的是：

- OCR 调用路径是否被触发；
- OCR 块插在何处；
- 扫描/损坏文档是否进入兜底。

它们**不证明**任何真实模型的中英文 OCR 准确率、表格重建正确率、公式转写质量、双栏阅读顺序、置信度校准或数据隐私。

## 9. 许可证、版本与近期活跃度

- 许可证：MIT（[官方 LICENSE](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/LICENSE)）；主包和 OCR 插件 `pyproject.toml` 也声明 MIT。
- 当前正式版：[`v0.1.7`](https://github.com/microsoft/markitdown/releases/tag/v0.1.7)，发布于 2026-07-29；固定提交与当日 `main` 相同。
- PDF 相关近期演进：
  - [`v0.1.5`](https://github.com/microsoft/markitdown/releases/tag/v0.1.5)（2026-02-20）：加入 aligned Markdown 表格、宽表格支持、部分编号修复。
  - [`v0.1.6`](https://github.com/microsoft/markitdown/releases/tag/v0.1.6)（2026-05-26）：加入内嵌图片/PDF scans 的 OCR layer，并修复 PDF 页面缓存导致的内存增长。
  - `v0.1.7` 仍在维护，但本次发布的公式修复主要位于 Office/OMML 方向，不应误算为 PDF 公式能力。
- 包元数据仍标为 Beta（[`packages/markitdown/pyproject.toml` L16-L24](https://github.com/microsoft/markitdown/blob/fd239d5d2be43d9b68329730206b9312c7d5a388/packages/markitdown/pyproject.toml#L16-L24)）。

结论：项目活跃，2026 年连续增强了 PDF 表格、扫描 OCR 插件和内存行为；但其“轻量 LLM 文本入口”定位没有变成“证据可追溯的高保真 PDF 文档模型”。

## 10. 供后续项目对比使用的判定表

| 维度 | 内置 PDF | `markitdown-ocr` 插件 | Azure 路径 |
|---|---|---|---|
| 运行方式 | 本地离线 | 视觉模型 API，取决于用户 client | Azure 云 API |
| 文本层 PDF | 强，轻量 | 可处理，但替换内置转换器 | 强 |
| 扫描 PDF | 不支持，空输出 | 支持嵌图 OCR；整文档空结果时 300 DPI 兜底 | 官方定位为高质量 OCR |
| 表格 | 启发式 Markdown 表格，适合表单/发票 | OCR 文本质量依赖模型，未形成结构化表格 contract | 官方定位更适合复杂表格 |
| 公式 | 无专门 PDF 公式路径 | 依赖视觉模型和 prompt，无稳定 LaTeX contract | 本次未深挖 Azure 服务自身公式 contract |
| 多栏 | 无专门栏/阅读顺序模型 | 主要按 y 排序，存在交错风险 | 官方称 cloud layout extraction |
| 图片 | PDF 内图片不描述 | OCR 文本，不是稳定语义图注 | 多模态能力更强 |
| 页码 | 内置不保留 | Markdown `## Page N` | CU 示例含 page comment |
| bbox/坐标 | 内部使用但不输出 | 内部使用但不输出 | MarkItDown 集成最终仍以 Markdown 为主，需另核 Azure 原始响应暴露程度 |
| 置信度 | 无 | 字段声明但默认服务不赋值、结果不输出 | 未在本报告声称 |
| 输出 contract | Markdown + optional title | Markdown + optional title | Markdown，可带 YAML fields（CU custom analyzer） |
| 成本 | 本地计算 | 模型调用成本 | Azure 计费 |
| 部署复杂度 | 低 | 中等，需要插件和视觉模型 client | 高，需要 Azure 资源/凭据 |

## 11. 建议的公平实测集

后续若要与任何自研 PDF→Markdown 项目进行结论性比较，应固定同一批真实 PDF，至少包含：

1. 单栏、双栏、三栏学术论文；
2. 文本页与扫描页混合的 PDF；
3. 中文扫描件、旋转页、低清和噪声页；
4. 有线/无线表格、跨页表格、合并单元格、表格标题和脚注；
5. 行内公式、独立公式、编号公式、矩阵和上下标；
6. 图、图注、图内文字、流程图与坐标图；
7. 100 页以上大文件，记录峰值内存、耗时和失败页；
8. 对每种模式分别计入依赖、网络、模型/Azure 成本和隐私边界。

评分应至少拆成：文本召回、阅读顺序、表格单元格正确率、公式语法/语义、图注绑定、页码/bbox 可追溯性、低置信度暴露、失败可恢复性、性能和部署成本。否则“能输出一份 Markdown”会掩盖不同工具在文档理解深度上的本质差别。
