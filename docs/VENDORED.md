# Vendored 第三方组件记录（供应链）

> 目的：记录仓库内 vendored 的第三方代码与模型权重来源、版本、许可与哈希，
> 便于合规审计、复现与升级追踪。对抗性审查 P2 项。

## 1. Vendored Python 包

| 组件 | 来源 | 版本 | 许可 | 内容 | 获取方式 |
|---|---|---|---|---|---|
| **RapidOCR 适配器** | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) | v3.4.x（README 记录，代码内无 `__version__`） | Apache-2.0 | `models/production/rapidocr-adapter/rapidocr/`（det/rec/cls + inference_engine + utils） | 从上游 vendored 复制 |
| **RapidTable 表格结构** | [RapidAI/RapidTable](https://www.modelscope.cn/models/RapidAI/RapidTable) / PyPI `rapid-table` | pip wheel `rapid_table-3.0.2` | Apache-2.0 | `models/production/table-adapter/rapid_table/`（pp_structure/table_matcher/inference_engine） | `pip download rapid-table==3.0.2` 后解包 vendored |

> ⚠️ 两个 vendored 副本内**均无 LICENSE 文件**（上游 Apache-2.0）。对外发布前需把上游 LICENSE 一并带上，并按各自授权条款合规。

## 2. 模型权重（均 gitignore，不入库）

| 权重 | 大小 | SHA256 | 来源 |
|---|---|---|---|
| `ch_PP-OCRv4_det_infer.onnx` | 4.7 MB | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` | RapidOCR default_models.yaml → modelscope.cn |
| `ch_PP-OCRv4_rec_infer.onnx` | 10.9 MB | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` | 同上 |
| `ch_ppocr_mobile_v2.0_cls_infer.onnx` | 0.6 MB | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` | 同上 |
| `slanet-plus.onnx` | 7.8 MB | `d57a942af6a2f57d6a4a0372573c696a2379bf5857c45e2ac69993f3b334514b` | `modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx` |

## 3. 字体

| 文件 | 大小 | SHA256 | 来源/许可提示 |
|---|---|---|---|
| `FZYTK.TTF`（方正姚体） | 3.2 MB | `4065a23df6823c8e2b69a0e76d02f02a6470b8774a5e91086609701ad95cc33f` | RapidOCR 随包分发，仅用于结果可视化；版权归原持有人，使用需遵守原授权 |

## 4. 供应链风险与缓解

1. **vendored 副本无 LICENSE**：需在发布时补齐上游 Apache-2.0 许可证文本。
2. **RapidTable 权重缺失时自动下载**：`rapid_table/model_processor/main.py` 的 `DownloadFile` 在权重缺失时从 modelscope.cn 下载，与项目"全离线"承诺矛盾。缓解：`pdf2md/table_model.py` 用 `model_missing:table` 闩锁优雅回退（不阻塞转换），但首次构造可能触发一次网络请求。如需严格离线，应在部署前确保权重就位。
3. **权重 gitignore → fresh clone 静默降级**：克隆仓库无权重时，表格走几何路径（SLANet 不可用），不影响转换但复杂表能力降级。建议在部署文档明示"需带上 models/production/*/models/ 权重目录"。
4. **版本追踪**：vendored 副本无版本标记，升级时按上表来源重新 vendored，并比对文件差异。
5. **eval 风险**：vendored 代码内 `eval()` 均在白名单断言后（config 来自 vendored YAML，受信任），PDF 内容不可控 → 不可利用。
