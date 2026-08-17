# PDF 阅读 Skill 基线测试（2026-08-16）

测试对象是尚未包含任何 `SKILL.md` 的提交 `8179730`。三名只读测试 Agent
分别模拟 Codex、Claude Code 和通用 Agent；测试期间没有修改仓库。

## 共同失败

- Agent 只有主动发现并阅读根 README 后，才可能执行 `ensure → Markdown → layout.json → render`。
- 仓库没有 Codex、Claude 或通用 Agent 可安装的 `SKILL.md`，因此 PDF 附件不会可靠触发转换。
- 缓存只比较修改时间，无法识别“内容已变化但时间戳相同”的 PDF。
- 文档要求“不要渲染整页”，但脚本实际支持 `full`；bbox 缺失、错误或裁切不全时，行为契约冲突。
- 没有标准的 `Markdown → bbox → 整页 → 相邻页` 兜底链。
- 没有区分 PDF 文件页序号和文档印刷页码标签。

## 三个基线原句

- Codex：`当前仓库能提供“手动遵循 README 后的 PDF→Markdown→页码回读流程”，但不能保证上传 PDF 后自动执行。`
- Claude Code：`不能发现、不能安装“Claude 专用 Skill”，且整页兜底链路会被现有文档阻断。`
- 通用 Agent：`在没有 SKILL.md 的通用 Agent 环境中，无法保证用户一附加 PDF 就自动触发绑定。`

## 目标行为

三种 Skill 都必须强制同一条主链：

1. 用户操作和接收的文件始终是原始 PDF。
2. Agent 收到 PDF 内容任务后先运行最高精度 `ensure`，主要阅读生成的 Markdown。
3. PDF 与 Markdown 的缓存绑定使用内容哈希和完整产物检查，而不只看修改时间。
4. 内容不确定时先用 `layout.json` 定位 bbox；bbox 不可靠时读取 PDF 整页；仍不足时读取相邻页。
5. PDF 原始视觉内容与 Markdown 冲突时，以 PDF 为最终依据。
6. 对外引用 PDF 文件页序号，并在存在页码标签时同时给出标签。

## WorkBuddy 补充基线

在没有 WorkBuddy 专用 Skill 和上传包时，测试 Agent 会把 WorkBuddy 错归为“其他 Agent
Skills 宿主”，建议安装通用版，并猜测 WorkBuddy 会扫描 `~/.agents/skills` 或某个未公开
的自定义目录。这个方案无法证明 WorkBuddy 能发现 Skill，也没有可通过“添加技能 → 上传
技能”导入的 ZIP。

测试 Agent 还指出：WorkBuddy 已有通用 PDF/OCR 路径时，模糊的触发描述不足以保证云枢
OCR 被选中；仓库移动后 `.yunshu-ocr-root` 会失效；附件路径、脚本执行和本地页面图片读取
都必须遵循 WorkBuddy 的授权工作空间与确认机制。

因此 WorkBuddy 版必须提供根层 `SKILL.md` 的上传 ZIP、强 PDF 内容触发描述、明确权限边界，
并在仓库路径变化时要求从新位置重新生成和上传包，不能猜测隐藏安装目录。
