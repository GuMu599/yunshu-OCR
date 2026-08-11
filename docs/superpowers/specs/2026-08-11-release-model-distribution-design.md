# GitHub Release 模型分发设计

## 目标

让用户在具备 Python 运行环境的前提下，通过一次显式安装从固定的 GitHub Release 获取模型；安装完成后的 PDF 转 Markdown 流程只使用本地模型，不访问网络、不调用云端服务，也不消耗大模型 token。

## 范围

本设计覆盖模型清单、Release 模型包、安装与校验命令、仓库相对模型路径、转换前严格预检、离线约束、回归测试和发布文档。

本设计不创建 GitHub Release、不上传远端、不打包 Python 解释器或系统运行库，也不把论文 PDF、测试输出、用户缓存目录或授权不明确的字体纳入公开资产。

## 用户流程

首次安装模型时允许联网：

```powershell
git clone https://github.com/cancelGuMu/yunshu-OCR.git
cd yunshu-OCR
python -m pdf2md.models install
```

安装完成后可断网转换：

```powershell
python -m pdf2md.cli input.pdf
```

用户可随时执行只读检查：

```powershell
python -m pdf2md.models status
python -m pdf2md.models verify
```

转换命令不会自动下载。模型缺失、GitHub Release 附件未安装、文件被篡改或版本不匹配时，转换在创建输出目录前失败，并给出 `python -m pdf2md.models install` 修复命令。

## 模型包契约

仓库新增 `models/models.lock.json`，作为模型供应链的唯一事实来源。清单采用版本化 JSON，包含：

- 清单格式版本。
- GitHub 仓库、固定 Release tag、固定附件名和下载 URL。
- Release 压缩包的字节数和 SHA-256。
- 每个模型的逻辑名称、压缩包内路径、仓库安装路径、字节数、SHA-256、来源、版本和许可证标识。

Release 使用固定 tag，不使用 `latest`，避免同一份代码在不同时间下载到不同模型。压缩包内只包含以下七个推理权重：

| 能力 | 安装路径 |
|---|---|
| DocLayout-YOLO | `models/runtime/layout/doclayout_yolo_docstructbench_imgsz1280_2501.pt` |
| pix2tex 主模型 | `models/runtime/pix2tex/weights.pth` |
| pix2tex 图像缩放 | `models/runtime/pix2tex/image_resizer.pth` |
| RapidOCR 检测 | `models/production/rapidocr-adapter/rapidocr/models/ch_PP-OCRv4_det_infer.onnx` |
| RapidOCR 识别 | `models/production/rapidocr-adapter/rapidocr/models/ch_PP-OCRv4_rec_infer.onnx` |
| RapidOCR 方向 | `models/production/rapidocr-adapter/rapidocr/models/ch_ppocr_mobile_v2.0_cls_infer.onnx` |
| RapidTable 结构 | `models/production/table-adapter/rapid_table/models/slanet-plus.onnx` |

`FZYTK.TTF` 不进入模型包。它只服务第三方结果可视化且授权边界不清晰；转换推理路径必须改成不初始化或下载可视化字体。

## 模块与接口

新增 `pdf2md/models.py` 作为模型管理模块。它隐藏下载、临时文件、安全解压、哈希计算和原子发布细节，只向调用者提供以下接口：

```python
load_manifest(path: Path | None = None) -> ModelManifest
model_status(manifest: ModelManifest | None = None) -> dict
verify_models(manifest: ModelManifest | None = None) -> dict
install_models(manifest: ModelManifest | None = None, *, source_url: str | None = None) -> dict
build_release_archive(output: Path, manifest: ModelManifest | None = None) -> dict
```

同一模块提供 `install`、`status`、`verify` 和 `build-release` 子命令。测试通过注入本地 `source_url` 或临时清单复用真实安装实现，不引入第二套测试下载器。

`pdf2md/layout.py` 默认从清单解析 DocLayout 路径。显式 `--layout-model` 和 `PDF2MD_LAYOUT_MODEL` 仍保留，但外部可执行 `.pt` 权重必须继续提供匹配的 SHA-256。

`pdf2md/formulas.py` 默认从清单解析 pix2tex 权重，不再把 `site-packages/pix2tex/model/checkpoints` 当作模型事实来源，也不向安装环境复制文件。pix2tex 包代码和配置由精确依赖版本提供，权重路径由项目显式传入加载流程。

RapidOCR 和 RapidTable 保持现有仓库相对路径，但哈希值改为从同一清单读取，避免代码常量和发布清单漂移。

## 安装安全

安装过程遵循以下顺序：

1. 从固定 Release URL 流式下载到仓库内临时文件，限制最大字节数并设置连接与读取超时。
2. 下载完成后验证压缩包字节数和 SHA-256。
3. 在临时目录安全解压，拒绝绝对路径、父目录穿越、符号链接、重复成员、未声明成员和超过清单上限的展开大小。
4. 逐个验证七个模型的路径、大小和 SHA-256。
5. 仅在全部验证通过后，将文件原子发布到目标路径。
6. 任一步失败都删除临时文件，不覆盖已经验证可用的旧模型。

安装器不得执行压缩包内代码，不加载 `.pt` 或 `.pth`，只按字节校验和移动文件。

## 转换离线与质量约束

正常转换默认启用离线环境变量，禁止 Hugging Face、Transformers、Albumentations 更新检查和 YOLO 自动安装。模型安装命令是仓库中唯一允许主动访问 Release URL 的入口。

默认转换在处理 PDF 前严格验证完整模型集。缺失或不匹配时不允许静默切换到低质量模型。以下现有选项视为用户显式降级意图：

- `--no-ocr`：明确关闭 OCR。
- `--no-table-model`：明确关闭 SLANet。
- `--formula-engine rapidocr`：明确放弃 pix2tex 公式模型。

DocLayout 始终是默认流水线的必需模型。用户显式注入测试版面检测器时，测试可以绕过 DocLayout 预检，但生产 CLI 不提供该绕过路径。

## Release 构建

`python -m pdf2md.models build-release --output tmp/pdf2md-models-v1.zip` 从已验证的本机模型源构建确定性 ZIP：成员按路径排序，时间戳、权限和压缩参数固定。相同输入必须生成相同 SHA-256。

构建命令按以下顺序定位源文件：显式 `--source-root` 下的清单相对路径、仓库中已经安装的目标路径、当前机器已知的旧 DocLayout/pix2tex 缓存路径。旧缓存兼容只存在于维护者构建命令中；安装、预检和转换运行时不得读取这些旧路径。无论源自何处，文件都必须先匹配清单中的逐文件大小和 SHA-256。

构建结果写入 `tmp/`，继续由 `.gitignore` 排除。构建命令输出附件名、字节数、SHA-256 和逐文件结果，供维护者更新 `models/models.lock.json` 后重新构建并校验。最终上传到 GitHub Release 的必须是该字节完全一致的 ZIP。

创建公开 Release 前必须确认 DocLayout-YOLO 和 pix2tex 权重允许再分发，并在 `docs/VENDORED.md`、`NOTICE` 和 `THIRD_PARTY_LICENSES/` 中保留适用条款。许可证证据不足时，代码可以提交，但公开上传模型包必须停止。

`requirements-lock.txt` 从干净的 Windows Python 3.13 环境生成，只包含项目运行与测试依赖的精确版本，不采集当前全局 Python 环境中的无关包。`requirements.txt` 保留兼容范围供开发使用；发布验证和回归测试使用锁文件，避免推理运行库升级导致结果漂移。

## 文件变更

新增：

- `models/models.lock.json`
- `pdf2md/models.py`
- `pdf2md/tests/test_models.py`
- `pdf2md/tests/test_conversion_offline.py`
- `scripts/build_model_release.ps1`
- `requirements-lock.txt`

修改：

- `.gitignore`
- `README.md`
- `docs/VENDORED.md`
- `NOTICE`
- `pdf2md/README.md`
- `pdf2md/cli.py`
- `pdf2md/formulas.py`
- `pdf2md/layout.py`
- `pdf2md/ocr.py`
- `pdf2md/pipeline.py`
- `pdf2md/table_model.py`
- 相关预检、CLI、公式和模型安全测试

## 测试策略

所有新增行为先写失败测试，再实现：

- 清单结构、路径唯一性、固定 Release tag 和 SHA-256 格式。
- 模型完整、缺失、截断、损坏和 Git LFS 指针文件状态。
- 下载超时、超过大小、压缩包哈希错误和临时文件清理。
- ZIP 路径穿越、绝对路径、符号链接、重复成员和额外成员拒绝。
- 安装失败保留旧模型；成功安装后七个文件全部匹配。
- DocLayout、pix2tex、RapidOCR、RapidTable 都从清单解析相同事实。
- 转换期间封禁 socket 后，完整本地模型路径不产生网络访问。
- 模型缺失时在创建输出目录前失败并给出安装命令。
- 四篇真实论文继续通过文本召回、阅读顺序、表格数量和公式 LaTeX 回归。

## 验收标准

1. 在没有旧模型缓存的目录中执行安装命令，可以从固定 Release 附件安装并验证七个模型。
2. 删除或篡改任一模型后，`verify` 返回非零退出码，默认转换不开始处理 PDF。
3. 安装完成后封禁网络，四篇真实论文仍通过现有回归标准。
4. 转换过程没有 HTTP 请求、模型下载、云端 API 调用或大模型 token 消耗。
5. 相同模型输入两次构建得到字节完全一致的 Release ZIP。
6. Git 提交不包含 Release ZIP、模型权重、测试 PDF、用户缓存或 `tmp/` 输出。
7. README 中的安装、离线语义、模型版本和失败模式与实际 CLI 一致。
