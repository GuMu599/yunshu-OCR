# Vendored 第三方组件记录（供应链）

> 目的：记录仓库内 vendored 的第三方代码与模型权重来源、版本、许可与哈希，
> 便于合规审计、复现与升级追踪。对抗性审查 P2 项。

## 1. Vendored Python 包

| 组件 | 来源 | 版本 | 许可 | 内容 | 获取方式 |
|---|---|---|---|---|---|
| **RapidOCR 适配器** | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) | v3.4.x（README 记录，代码内无 `__version__`） | Apache-2.0 | `models/production/rapidocr-adapter/rapidocr/`（det/rec/cls + inference_engine + utils） | 从上游 vendored 复制 |
| **RapidTable 表格结构** | [RapidAI/RapidTable](https://www.modelscope.cn/models/RapidAI/RapidTable) / PyPI `rapid-table` | pip wheel `rapid_table-3.0.2` | Apache-2.0 | `models/production/table-adapter/rapid_table/`（pp_structure/table_matcher/inference_engine） | `pip download rapid-table==3.0.2` 后解包 vendored |

> 两个 vendored 副本内均无独立 LICENSE 文件；仓库已在
> `THIRD_PARTY_LICENSES/Apache-2.0.txt` 随附 Apache-2.0 全文，并在根目录
> `NOTICE` 中声明第三方授权边界。上游版权声明和源码文件内已有声明仍需保留。

## 2. 模型 Release（权重均 gitignore，不入 Git 历史）

固定发布坐标：`models-v1/pdf2md-models-v1.zip`。

- ZIP 大小：`185346805` bytes
- ZIP SHA256：`daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0`
- 解包后总大小：`185344721` bytes
- 唯一清单：`models/models.lock.json`

安装器先校验 ZIP 大小与哈希，再拒绝路径穿越、符号链接、重复项和未声明成员，最后逐文件校验并原子替换。ZIP 还包含经清单声明和哈希保护的模型署名说明、AGPLv3、CC BY-NC-SA 4.0 与 Apache-2.0 文本。
转换阶段不调用任何上游下载器。

| 权重（安装路径） | 大小 | SHA256 | 来源 / 上游标注许可 |
|---|---:|---|---|
| `models/runtime/layout/doclayout_yolo_docstructbench_imgsz1280_2501.pt` | 39.8 MB | `1b152460888dc30be6db7f5dfab28bde3dcc999e5202f46187a764a1699c80be` | DocLayout-YOLO DocStructBench 1280 checkpoint / AGPL-3.0-only |
| `models/runtime/pix2tex/weights.pth` | 102.1 MB | `a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa` | LaTeX-OCR weights Release v0.0.1 / CC-BY-NC-SA-4.0 |
| `models/runtime/pix2tex/image_resizer.pth` | 19.4 MB | `1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458` | LaTeX-OCR weights Release v0.0.1 / CC-BY-NC-SA-4.0 |
| `ch_PP-OCRv4_det_infer.onnx` | 4.7 MB | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` | RapidOCR default_models.yaml → modelscope.cn |
| `ch_PP-OCRv4_rec_infer.onnx` | 10.9 MB | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` | 同上 |
| `ch_ppocr_mobile_v2.0_cls_infer.onnx` | 0.6 MB | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` | 同上 |
| `slanet-plus.onnx` | 7.8 MB | `d57a942af6a2f57d6a4a0372573c696a2379bf5857c45e2ac69993f3b334514b` | `modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx` |

## 3. 字体

| 文件 | 大小 | SHA256 | 来源/许可提示 |
|---|---|---|---|
| `FZYTK.TTF`（方正姚体） | 3.2 MB | `4065a23df6823c8e2b69a0e76d02f02a6470b8774a5e91086609701ad95cc33f` | 仅见于本地 RapidOCR 可视化资产；不进入模型 Release，转换推理不使用 |

## 4. 供应链风险与缓解

1. **vendored 副本无独立 LICENSE**：仓库已集中随附 Apache-2.0 全文；发布流程仍需确保 `NOTICE`、`THIRD_PARTY_LICENSES/` 和源码内版权声明一并分发。
2. **上游代码含下载能力**：RapidTable、RapidOCR、pix2tex 和 DocLayout 的上游代码仍含下载逻辑；本项目通过转换前严格清单校验、固定本地路径、离线环境变量和禁 socket 回归测试，阻止转换路径触发这些逻辑。
3. **fresh clone 无权重**：这是显式未安装状态，不再静默降级。运行 `python -m pdf2md.models install` 后必须由 `verify` 返回成功，转换才会创建输出。
4. **版本追踪**：vendored 副本无版本标记，升级时按上表来源重新 vendored，并比对文件差异。
5. **eval 风险**：vendored 代码内 `eval()` 均在白名单断言后（config 来自 vendored YAML，受信任），PDF 内容不可控 → 不可利用。
6. **Release 再分发核验**：DocLayout 1280 权重为 `AGPL-3.0-only`；pix2tex 代码虽为 MIT，但两个权重由官方 Release 单独授权为 `CC-BY-NC-SA-4.0`。完整证据、条件与商业限制见 `docs/research/model-release-redistribution-audit-2026-08-11.md`。

## 5. Release 构建与发布门禁

```powershell
powershell -File scripts/build_model_release.ps1 -Output tmp/pdf2md-models-v1.zip
python -m pdf2md.models install --source-url file:///E:/Codex/yunshu-OCR/tmp/pdf2md-models-v1.zip
python -m pdf2md.models verify
```

构建结果必须与 `models/models.lock.json` 中的 ZIP 大小和 SHA256 完全一致。当前非商业开源版 ZIP
已携带模型许可证、署名与 provenance 文件；发布说明仍须突出 pix2tex 权重的非商业限制。
发布后用全新 clone 验证固定 URL，再运行完整测试和真实 PDF 回归。
