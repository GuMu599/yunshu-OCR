# WorkBuddy Agent Skill 适配研究（2026-08-16）

## 结论

用户口中的“Workbody”应指腾讯的 **WorkBuddy**。其官方定位是“全场景 AI
办公工作台”，支持自然语言任务、自主规划、本地文件操作、文档和图表处理；这与
“很多人用它处理 PDF”的描述完全吻合。另一个同名的 `workbuddy.com` 是现场服务与
工单管理软件，不是本次要适配的 AI Agent。

建议新增版本统一命名为 **WorkBuddy 版**，不要继续使用 `Workbody` 拼写。

官方来源：

- WorkBuddy 产品页：<https://cloud.tencent.com/product/workbuddy>
- WorkBuddy 官方简介：<https://www.workbuddy.cn/docs/workbuddy/Overview>
- 同名但无关的现场服务产品：<https://workbuddy.com/>

## 1. 官方产品、文档和仓库

### 1.1 官方名称与入口

- 产品正式名称是 `WorkBuddy`，产品页写明它由腾讯推出，覆盖日常办公、代码开发和
  设计创意。
- 官方文档站是 `workbuddy.cn/docs/workbuddy/`。
- 官方产品站包括 `workbuddy.ai` 和腾讯云产品页。

来源：

- <https://www.workbuddy.ai/>
- <https://cloud.tencent.com/product/workbuddy>
- <https://www.workbuddy.cn/docs/workbuddy/Overview>

### 1.2 公开仓库状态

WorkBuddy 桌面产品本身没有在官方文档中提供开源客户端仓库。腾讯公开了与产品相关
的官方仓库，但这些仓库不能当作 WorkBuddy 客户端源码：

- `Tencent/workbuddy-bench`：WorkBuddy Bench 评测框架。其 README 明确在
  `.agents/skills/` 放置 `SKILL.md` Skill，并把 `.claude/skills/` 链接到同一份
  Skill；这证明腾讯相关 Agent 工作流采用标准的 `SKILL.md` 目录结构。
- `Tencent/BrowserSkill`：腾讯官方浏览器 Skill，根目录 `skill/SKILL.md` 的
  frontmatter 使用 `name` 和 `description`。
- `TencentEdgeOne/awesome-website-prompts-and-skills`：腾讯 EdgeOne 维护、同时作为
  “WorkBuddy × Tencent EdgeOne AI Prompts × Skills 挑战赛”官方作品池；README
  明确写明其中 Skills 遵循 Anthropic Skills 规范，并推荐在 WorkBuddy 中使用。

来源：

- <https://github.com/Tencent/workbuddy-bench>
- <https://github.com/Tencent/BrowserSkill/blob/main/skill/SKILL.md>
- <https://github.com/TencentEdgeOne/awesome-website-prompts-and-skills>

## 2. WorkBuddy 的 Skill 安装与包格式

### 2.1 用户侧安装入口

官方安装路径是：

1. 打开 WorkBuddy 的“技能”页面。
2. 点击“添加技能”。
3. 选择“上传技能”。
4. 拖拽或选择本地技能包。
5. 导入后由系统自动完成配置。

同一页面还支持“查找技能”“创建技能”、启用、关闭和卸载。官方没有公开稳定的
本地 Skill 安装目录，因此 README 不应指导用户把文件复制到某个隐藏目录；应交付
可直接通过 UI 上传的技能包。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Practice-Cases/Practice-Eight>

### 2.2 个人上传核心是 `SKILL.md`，企业后台可带 `manifest.yaml`

WorkBuddy 个人端和 SkillHub 的官方证据一致指向 Agent Skills 目录结构，核心要求是
ZIP 或文件夹根层存在 `SKILL.md`：

截至 2026-08-16，对 WorkBuddy 官方 sitemap 列出的 84 个桌面产品文档页面进行检索，
没有发现 `manifest.yaml`、`manifest.yml` 或 `_meta.json` 的作者配置说明。这进一步说明
不应为 WorkBuddy 版自行发明 manifest；平台可识别的核心仍是 `SKILL.md`。

```text
yunshu-ocr/
├── SKILL.md          # 必需，放在包根目录
├── scripts/          # 可选
├── references/       # 可选
└── assets/           # 可选
```

腾讯 SkillHub 的发布界面要求文件夹或 ZIP 中必须包含根层 `SKILL.md`。从 SkillHub
下载“腾讯文档”官方认证 Skill 时，响应类型是 `application/zip`，压缩包根层含：

- `SKILL.md`
- 脚本和参考文件目录
- `_meta.json`

因此 WorkBuddy 版最稳妥的发布物是 ZIP，解压后根层直接出现 `SKILL.md`，不要再套一层
无意义目录。

SkillHub 官方认证“腾讯文档”包的 `_meta.json` 实测字段如下：

```json
{
  "ownerId": "528712",
  "slug": "tencent-docs",
  "version": "1.0.41",
  "publishedAt": 1784099079030
}
```

这份 `_meta.json` 是 SkillHub 下载包的发布来源元数据，不是作者手写的安装清单。云枢
OCR 自行打包时不应伪造 `ownerId` 或 `publishedAt`；除非未来通过 SkillHub 正式发布并
由平台生成，否则无需附带 `_meta.json`。

腾讯云 WorkBuddy Enterprise 的企业 Skill 管理文档另行给出
`SKILL.md + manifest.yaml + scripts/references/assets` 包结构和 manifest 最小示例。因此，
云枢 ZIP 可以在根层附带 `manifest.yaml` 作为企业后台兼容元数据，但不能把它写成个人
WorkBuddy 上传的强制要求。

来源：

- WorkBuddy Skill 上传：<https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market>
- WorkBuddy Enterprise Skill 管理：<https://cloud.tencent.com/document/product/1831/134420>
- SkillHub 官方认证 Skill 文件清单：<https://api.skillhub.cn/api/v1/skills/tencent-docs/files?namespace=tencent-adm>
- SkillHub 官方认证 Skill 元数据：<https://api.skillhub.cn/api/v1/skills/tencent-docs?namespace=tencent-adm>
- SkillHub 官方下载包：<https://api.skillhub.cn/api/v1/download?slug=tencent-docs>
- 腾讯官方 Agent Skills 示例：<https://github.com/Tencent/BrowserSkill/blob/main/skill/SKILL.md>

### 2.3 `SKILL.md` frontmatter

官方 WorkBuddy 文档没有单独发布“必填字段表”。腾讯官方 Skill 示例使用的最小字段是：

```yaml
---
name: yunshu-ocr
description: >-
  当用户上传或引用 PDF，并要求阅读、总结、问答、提取、比较、引用或按页核验时，
  优先用云枢 OCR 将原 PDF 绑定为最高精度 Markdown；Agent 主要读取 Markdown，
  不确定时按页码回读 PDF 原始视觉内容。
---
```

SkillHub 官方认证“腾讯文档”包还使用了 `homepage`、`version`、`author` 和 `metadata`，
但这些是扩展字段，不应误写成 WorkBuddy 的强制要求。对于云枢 OCR，建议保留：

- 必需：`name`、`description`
- 建议：`version`、`author`、`homepage`
- 个人上传不依赖 `manifest.yaml`；需要兼容 Enterprise 后台时可附带官方最小字段

`description` 是 WorkBuddy 路由此 Skill 的关键。官方自定义 Skill 指南要求把“能力、
触发方式和输出结果”说清楚；云枢 OCR 应在描述中覆盖 PDF 阅读、总结、问答、提取、
比较、页码引用和错误核验等意图。

来源：

- 腾讯 BrowserSkill frontmatter：<https://github.com/Tencent/BrowserSkill/blob/main/skill/SKILL.md>
- WorkBuddy 创建自定义 Skill：<https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Practice-Cases/Practice-Eight>
- SkillHub 官方认证 Skill 下载包：<https://api.skillhub.cn/api/v1/download?slug=tencent-docs>

### 2.4 WorkBuddy Enterprise `manifest.yaml`

腾讯云的 WorkBuddy Enterprise 文档明确规定：企业管理员上传的 `.zip` Skill 包中，
`SKILL.md` 和 `manifest.yaml` 均为必填。官方最小 manifest 只包含五个字段：

```yaml
name: yunshu-ocr
version: 1.0.0
description: "云枢 OCR 高精度 PDF 转 Markdown、绑定阅读与按页核验 Skill"
category: document-processing
author: Gumu
```

字段用途按官方示例可直接理解为：

- `name`：Skill 标识。
- `version`：版本号。
- `description`：Skill 简要说明。
- `category`：企业后台的业务分类标识。
- `author`：作者或企业管理员标识。

企业后台上传表单还会单独要求“Skill 标识、显示名称、分类”，版本和描述可选，并配置
可见范围。也就是说，manifest 不替代后台权限和分发策略。对于同时面向个人版和企业版
的云枢 ZIP，可以附带上述 manifest；个人 WorkBuddy 的“上传技能”仍以根层
`SKILL.md` 为核心。

来源：

- <https://cloud.tencent.com/document/product/1831/134420>

## 3. PDF 附件和本地文件访问

### 3.1 PDF 输入方式

WorkBuddy 官方支持：

- 点击上传按钮选择文件；
- 把文件直接拖入对话框；
- 通过 `@` 引用文件或规则；
- 为任务选择本地工作空间，然后直接读取该目录中的文件。

官方列出的支持格式包括 PDF、Word、TXT、Markdown、RTF、Excel、CSV、TSV、PPT、
常见图片、ZIP/RAR 和代码文件。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/Conversation>
- <https://www.workbuddy.cn/docs/workbuddy/Create-Task>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Practice-Cases/Practice-One>

### 3.2 PDF 内置能力与路由冲突

WorkBuddy 已内置办公文档 Skills，其中 `pdf` Skill 支持：

- 正文提取
- 表格提取
- OCR
- 拆分合并
- 表单处理

技能市场截图还显示 `MarkItDown` 和“腾讯云通用文字识别 OCR”等技能。因此云枢 OCR
不能只写成泛泛的“PDF 工具”，否则可能被内置 `pdf`、MarkItDown 或其它 OCR Skill
抢走路由。WorkBuddy 版应明确声明：

1. 当任务是阅读、总结、问答、检索、提取、比较或引用 PDF 内容时，优先使用云枢 OCR。
2. 保留用户的原始 PDF，不把 Markdown 当成用户交付物。
3. Agent 主要读取绑定的 Markdown。
4. Markdown 不可靠时执行 `layout.json → bbox → PDF 整页 → 相邻页` 回读。
5. PDF 原始视觉内容与 Markdown 冲突时，以 PDF 为最终证据。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/WorkBuddy-Zero-Cost-Skill-Top-10/Office-Document-Suite>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market>

### 3.3 用户看到 PDF，Agent 读取 Markdown 的实现边界

WorkBuddy 的结果区能够显示工作空间文件、产物和文件变更，也能预览 Word、Markdown、
PDF 等结果。为了实现“用户仍操作 PDF、Agent 读 Markdown”，WorkBuddy 版应：

- 把用户提供的 PDF 视为主对象和最终引用来源，不覆盖、不改名、不修改；
- 在当前授权工作空间创建稳定的派生目录，保存 Markdown、`layout.json`、`report.json`
  和按需渲染的页面图片；
- 默认只在内部工作流程中读取派生 Markdown，不主动把 Markdown 作为主要产物推给用户；
- 对外回答始终引用“PDF 文件第 N 页”，存在印刷页码标签时同时说明标签；
- 用户要求看原文或转换结果可疑时，直接打开/渲染对应 PDF 页。

官方没有提供“隐藏派生文件”的专门 API，因此所谓“用户只看到 PDF”应理解为产品交互
主对象和回答来源仍是 PDF，而不是保证 WorkBuddy 文件树绝对不显示 Markdown。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/Results>
- <https://www.workbuddy.cn/docs/workbuddy/Conversation>

## 4. 权限、隐私和运行约束

### 4.1 工作空间和文件权限

官方说明：

- 文件处理默认在本地完成，原始数据不上传云端；服务端只处理数据片段，用后即弃。
- WorkBuddy 只能访问用户主动授权的文件夹。
- 系统敏感目录会被拦截，高风险操作需要二次确认。
- 工作空间是当前任务主要读取和保存文件的目录。

因此云枢 OCR 的 Markdown、映射、质量报告和页面渲染结果必须优先写入当前工作空间，
不能依赖访问用户未授权的全局缓存目录。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/Conversation>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Permission-Modes>

### 4.2 脚本、网络和外部程序

默认权限模式下，下列动作可能弹出确认：

- 执行脚本、命令或外部程序；
- 网络访问；
- 写入受保护路径；
- 高风险删除或批量修改。

云枢 OCR 版不应要求用户开启 Full Access。首次运行转换器、安装依赖或下载模型时，允许
WorkBuddy 按默认权限显示确认，并在 Skill 指令中解释用途。所有转换结果应写入可恢复、
隔离的工作空间目录。

官方文档没有承诺预装 Python 或其它特定运行时，因此 Skill 应先检查仓库现有脚本所需
运行时；缺失时按 WorkBuddy 的确认机制安装，而不是静默降级到低精度 PDF 解析器。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Permission-Modes>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market>

### 4.3 大文件和平台支持

- Windows：Windows 10 及以上。
- macOS：macOS 12 及以上；M 系列使用 ARM64，Intel 使用 X64。
- 官方没有公布 PDF 的固定大小或页数上限。文档只建议上传失败时检查格式，较大文件可
  压缩或拆分。因此不能在云枢 README 中自行声称一个未经证实的硬上限。

来源：

- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Installation-Win-Guide>
- <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Installation-Mac-Guide>
- <https://www.workbuddy.cn/docs/workbuddy/Conversation>

## 5. 对云枢 OCR WorkBuddy 版的实现要求

建议按下面的最小适配面实施：

1. 新增 `skills/workbuddy/yunshu-ocr/SKILL.md`，复用现有最高精度转换和页码回读脚本。
2. 将 `description` 写成 WorkBuddy 专用的强触发描述，覆盖所有 PDF 内容任务，明确优先于
   通用 PDF/OCR/MarkItDown 流程。
3. 保留固定主链：`PDF → ensure → Markdown → layout 定位 → bbox → 整页 → 相邻页`。
4. 原始 PDF 永不修改；派生物写入当前工作空间中的独立目录，并用 SHA-256 维持绑定。
5. 不要求 Full Access；首次脚本执行、网络下载或安装依赖时接受默认权限确认。
6. 打包为 ZIP，压缩包根层直接包含 `SKILL.md` 和 `scripts/`。
7. ZIP 根层可附带 WorkBuddy Enterprise 官方格式的 `manifest.yaml`，但个人上传仍以
   `SKILL.md` 为核心；若未来经 SkillHub 发布，由平台生成 `_meta.json`。
8. README 与 AI_README 增加第四种选择，并只指导用户通过
   “技能 → 添加技能 → 上传技能”安装 WorkBuddy ZIP。

## 6. 可直接采用的 WorkBuddy frontmatter 示例

```yaml
---
name: yunshu-ocr
description: >-
  WorkBuddy 中的高精度 PDF 阅读与核验 Skill。用户上传、拖入、引用或指定 PDF，
  并要求阅读、总结、问答、检索、提取、比较、翻译、引用、表格/公式/图表识别、
  页码定位或原文核验时，优先使用本 Skill，而不是内置 pdf、MarkItDown 或普通 OCR。
  始终保留原始 PDF 给用户，将其转换并绑定为最高精度 Markdown 供 Agent 主要阅读；
  Markdown 缺失、可疑或与问题冲突时，按 layout.json 定位 PDF 局部区域，必要时回读
  整页和相邻页。Markdown 与 PDF 冲突时以 PDF 原始视觉内容为准。
version: 1.0.0
author: Gumu
homepage: https://github.com/GuMu599/yunshu-OCR
---
```

最终包结构建议：

```text
yunshu-ocr-workbuddy.zip
├── SKILL.md
├── manifest.yaml
└── scripts/
    └── yunshu_pdf.py
```

如果包内还需要许可证或使用说明，可增加 `LICENSE` 和 `README.md`，但 `SKILL.md` 必须
位于 ZIP 根层。
