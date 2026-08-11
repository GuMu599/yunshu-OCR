# 模型 Release 再分发许可核验

核验日期：2026-08-11

范围：`models-v1/pdf2md-models-v1.zip` 中仍待确认的 DocLayout-YOLO 与
pix2tex / LaTeX-OCR 权重。本文记录工程合规判断，不构成法律意见。

## 结论

初始 Release 方案不能按旧清单和 NOTICE 直接发布，因为两个许可证字段存在事实错误：

1. DocLayout-YOLO 1280 checkpoint 应记录为 `AGPL-3.0-only`，不是
   `AGPL-3.0-or-later`。
2. pix2tex 的代码是 MIT，但 `weights.pth` 和 `image_resizer.pth` 的官方
   Release 明确把权重授权为 `CC-BY-NC-SA-4.0`，不是 MIT。

修正许可记录、署名、许可证全文与发布说明后：

- DocLayout checkpoint 可以按 AGPLv3 条件原样再分发，商业使用本身不被禁止，
  但必须履行 AGPL 的通知、许可证与对应源代码义务。
- pix2tex checkpoint 只适合非商业分发和非商业使用；若项目或下游用途主要面向
  商业利益或金钱报酬，必须取得权利人的额外许可，或者从默认模型包中移除/替换。

## 1. DocLayout-YOLO DocStructBench 1280 checkpoint

### 文件身份

本项目文件：

- 文件：`doclayout_yolo_docstructbench_imgsz1280_2501.pt`
- 大小：`39772550` bytes
- SHA-256：`1b152460888dc30be6db7f5dfab28bde3dcc999e5202f46187a764a1699c80be`

精确官方模型页：

- <https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501>
- 模型 API：<https://huggingface.co/api/models/juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501>
- 模型卡原文：<https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501/raw/main/README.md>
- LFS 指针：<https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501/raw/main/doclayout_yolo_docstructbench_imgsz1280_2501.pt>

官方 API 与 LFS 元数据给出的大小和 SHA-256 与本项目文件完全一致，因此文件来源得到
密码学级匹配确认。

### 许可证判断

精确模型卡只写明：

```yaml
license: agpl-3.0
```

它没有出现“or any later version”授权语句，因此应使用现代 SPDX 标识
`AGPL-3.0-only`，不能扩大为 `AGPL-3.0-or-later`。

官方源码仓库也采用 AGPLv3：

- <https://github.com/opendatalab/DocLayout-YOLO>
- <https://github.com/opendatalab/DocLayout-YOLO/blob/main/LICENSE>

项目成员 JulioZhao97 在官方许可证 issue 中明确说明：

> AGPL-3.0 is correct (because Ultralytics YOLO requires AGPL-3.0).

来源：

- <https://github.com/opendatalab/DocLayout-YOLO/issues/110#issuecomment-2727825741>
- <https://github.com/opendatalab/DocLayout-YOLO/issues/110#issuecomment-2731369933>

因此不能采用旧模型页或其他 checkpoint 曾出现的 Apache-2.0 标注。

### 再分发条件与残余风险

AGPLv3 允许在满足许可证条件时复制和传递。Release 至少应：

- 保留模型名称、作者/项目来源、版本、大小和 SHA-256；
- 附 AGPLv3 全文和无担保声明；
- 提供官方模型页与对应源码链接；
- 不用仓库许可证重新授权该 checkpoint；
- 继续固定哈希，因为 PyTorch `.pt` 使用 pickle 结构，加载不可信文件可能执行代码。

训练数据仍有不能由公开资料彻底消除的权属风险。论文说明 M6Doc 因版权限制没有开源，
DocStructBench 的文档来源包含机构、出版商和网站：

- <https://arxiv.org/html/2410.12628v1#S2.SS2>
- <https://arxiv.org/html/2410.12628v1#S5.SS1>

一般开源项目可按上述条件接受此风险；如要求商业法律级的明确担保，应取得
OpenDataLab 或模型作者允许第三方原样镜像该 checkpoint 的书面确认。

## 2. pix2tex / LaTeX-OCR checkpoints

### 文件身份

本项目文件：

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `weights.pth` | `102113875` | `a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa` |
| `image_resizer.pth` | `19441973` | `1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458` |

官方权重 Release：

- <https://github.com/lukas-blecher/LaTeX-OCR/releases/tag/v0.0.1>
- GitHub API：<https://api.github.com/repos/lukas-blecher/LaTeX-OCR/releases/tags/v0.0.1>

官方 Release 的两个资产名称与大小均与本项目完全一致。当前 pix2tex 0.1.4 包中的
checkpoint 文件也与本项目上述 SHA-256 完全一致。GitHub 对这些旧资产没有提供官方
SHA-256 digest，因此这里是官方 URL、名称、大小、包内文件和项目哈希的联合来源确认，
不是由上游公布校验和完成的独立哈希复核。

### 许可证判断

LaTeX-OCR **源代码**采用 MIT：

- <https://github.com/lukas-blecher/LaTeX-OCR/blob/main/LICENSE>

但官方 `v0.0.1` Release 对两个**权重**单独声明：

> Since the model was trained on arxiv data the weights are released under
> CC BY-NC-SA.

因此两个 checkpoint 的许可证是：

- `Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International`
- SPDX：`CC-BY-NC-SA-4.0`
- 法律文本：<https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode>

代码 MIT 不能覆盖或替换权重的 CC BY-NC-SA 条款。

### 再分发条件

非商业原样再分发至少需要：

- 署名 Lukas Blecher / LaTeX-OCR，并链接官方项目和权重 Release；
- 标明两个权重采用 `CC-BY-NC-SA-4.0`；
- 附许可证链接或全文；
- 保留权利人提供的版权、许可和免责声明信息；
- 如修改权重，明确标记修改，并按相同许可证分享改编材料；
- 不把权重描述为 MIT、AGPL，或本项目自行授权的资产。

`NonCommercial` 限制的是主要面向商业利益或金钱报酬的使用。公开、免费 GitHub Release
不自动等于商业使用，但如果该模型包服务于收费软件、付费服务、商业交付或其他商业目的，
不能仅依赖此许可证。需要商业使用时应取得作者额外授权，或更换为允许商业使用的公式模型。

## 3. 对当前 Release 方案的必要整改

发布 `models-v1` 前至少完成以下事项：

1. 将 `models/models.lock.json` 中 DocLayout 改为 `AGPL-3.0-only`。
2. 将两个 pix2tex 权重改为 `CC-BY-NC-SA-4.0`，来源版本改为官方权重
   Release `v0.0.1`；`pix2tex==0.1.4` 是加载代码版本，不是权重 Release 版本。
3. 同步修正 `README.md`、`NOTICE` 和 `docs/VENDORED.md`。
4. 在 `THIRD_PARTY_LICENSES/` 增加 AGPLv3 与 CC BY-NC-SA 4.0 法律文本，
   并增加权重署名/来源记录。
5. 不要把整个混合 ZIP 声明成单一许可证；逐文件保留独立许可证。
6. 最稳妥的做法是在 ZIP 内包含许可证和 provenance 文件。当前安装器拒绝未声明成员，
   因此需要先让 manifest 显式声明这些元数据文件，再重建 ZIP、更新大小和 SHA-256。
7. 如果项目需要允许商业使用，默认 Release 不应包含当前 pix2tex 权重；应取得额外许可，
   或设计不含 pix2tex 的商业安全模型包/替代公式引擎。

## 最终发布判断

| 资产 | 当前能否公开镜像 | 条件 |
|---|---|---|
| DocLayout-YOLO 1280 checkpoint | 可以，有条件 | `AGPL-3.0-only` 合规材料与对应源代码指引；训练数据风险不作零风险担保 |
| pix2tex 两个 checkpoint | 仅限非商业，有条件 | `CC-BY-NC-SA-4.0` 署名、许可通知、相同方式共享改编材料 |
| 修正后的非商业 `pdf2md-models-v1.zip` | 可以，有条件 | ZIP 随附逐资产署名与三份许可证；发布说明必须突出 pix2tex 非商业限制 |
