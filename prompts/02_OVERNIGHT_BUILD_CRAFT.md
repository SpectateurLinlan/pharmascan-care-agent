# WorkBuddy Session 2 — Craft: SAFE UNATTENDED NIGHT BUILD (2026-10-13)

今晚我无法回复，所以请在不越权的前提下**持续推进多个可逆的仓库内任务**，不要每建一个文件就停下来问“是否继续”。但权限批准、不可逆操作或云端收费必须由真人处理，不能绕过授权。

## 一、必须先执行：读取完整项目约束（不可省略）

工作目录：**当前项目根目录**，先 `pwd` / `git status` / `git remote -v` 并确认是真实仓库。

在开始任何代码修改前，必须显式读取并遵守：

1. AGENTS.md
2. CODEBUDDY.md
3. .codebuddy/rules/engineering/RULE.mdc
4. 00_START_HERE.md

**按顺序读**：`00_START_HERE.md`、`PROJECT_BRIEF.md`、`docs/MASTER_SPEC.md`、`docs/ARCHITECTURE.md`、`docs/WORKFLOWS.md`、`docs/API_CONTRACTS.md`、`docs/DATA_MODEL.md`、`docs/SAFETY_AND_EVALUATION.md`、`docs/BUILD_PLAN.md`、`docs/SUBMISSION.md`。当且仅当需要对比才看 `docs/reference/*`，不把旧方案覆盖新方案。**先回复简短的实际代码现状、将修改的组件、公开接口和安全约束清单，再开始编辑。**

请在开始执行前，用不超过 10 条简短 bullet 确认：
- 你实际读取到了上述文件；
- 哪些工程规则会约束本次改动；
- Git push 被严格禁止；
- 本轮只允许仓库内可逆操作
不要只声称“已遵守”，如果文件不存在或无法读取，要明确报告。

本项目唯一主故事：患者通过含来源的用药登记建立 Active/Historical Regimen；可选照片图库与 Stage2 实现视觉相似性辅助；Daily Smart Check 不强制每剂拍照；区分视觉结果与用户自述服药；Agent 以 Tool Calling、状态持久化、追问/拒识和后续任务支持长期管理；六项 Challenge 2 具备最小覆盖证据。**不要实现医生端、真实 Singpass/NEHR、Tencent ADP、全新 Stage2/Blister 模型。**

## 二、允许你今夜自主完成的 P0 工作（按顺序、逐一验收）

**Gate 0 · Repo & contracts (先检查，避免覆盖队友已有文件)**
- 审计现有文件，不重建已存在模块，不直接改 Stage2 另一位负责人代码/权重。
- 生成后端干净分层 `domain / application / contracts / infrastructure-adapters / transport / agent / tests`，不要单文件 monolith。前端若无代码则建立最小 React TS Vite PWA 骨架。
- 编写 `README.md`, `.env.example`, package/pyproject dependencies，明确 env 配置与开发命令，绝不写入真实密钥。创建 ADR/contract test 文档。

**Gate 1 · Database and medication slice**
- 使用 PostgreSQL migrations 编写 P0 核心表（patient_profiles, products, source_documents/fields, patient_medications, regimen_versions, rules/occurrences, dose_events），严谨 PK/FK/RLS/索引/唯一约束；没有 Supabase key 只生成迁移并跑本地/隔离测试，不声称已部署。
- Pydantic DTO + injected repo interfaces + versioned medication service，支持 `draft → user-reviewed active regimen → history`, missing instructions pending, no inferred dose.
- 实现 `due occurrence → patient self-report taken/not_taken/unsure`, `visual_status=not_checked` when no photo; idempotency key prevents double event. Seed deterministic synthetic patient scenario only.
- 如果没有 PostgreSQL 运行环境，用轻量 fake repository 单元测试 + SQL migration static checks，记录环境限制；**不要偷偷改成只支持 SQLite 的最终方案。**

**Gate 2 · Stage2 adapter and safety**
- 读取 `docs/API_CONTRACTS.md` 和真实可见 OpenAPI。只写可测试 adapter，不猜 response shape；建立可替换的 `VisionPort` / FakeVisionProvider（必须明显标记 SIMULATED）/ HTTP implementation with timeouts, bounded retries, schema failure.
- 为单颗 TEVA 被 `/scan` 错识别为两个重叠 box 的 bug 写 **回归负例测试**；未修好只支持 single-pill controlled crop，不做多颗剂数认证。分开 personal reference 与 US catalogue candidate，谨慎版本化 256-d vector。
- 独立 policy 模块（纯函数）阻止 `wrong/discontinued/unknown/duplicated dose`, 防止模型 score = 概率、影像→真实身份与自动更新处方；不代替用户核对。

**Gate 3 · Minimal Agent and event evidence（今晚研发重点）**
- 实现一个有状态单 Agent Orchestrator / ToolRegistry，类型化 tool request/result，公开 Tool Port，LLM provider injected；若无真实模型 key，用可验证但**显式标记 deterministic-demo** 的简化 IntentRouter 接接口，不能称为真实 LLM Agent 测试通过。
- 至少跑通自动/测试路由：`enroll_medication`、`check_due_dose`、`record_self_report`、`get_dose_history`, `identify_unknown` 的待确认占位。出现图像不可靠时 ask clarification、持久化 unresolved、next_action；用真实实现的工具/数据库而非 4 段预写回答。
- Agent 无权直接访问 ORM/数据库或未经确认的写操作；安全策略与 Auth 由外部 application services 强制执行。日志仅记录脱敏 tool name/status/rule/model versions。
- 编写端到端集成测试：手动录入 → 新版本/创建计划 → 用户报告吃药 → 再次查询历史与工具轨迹；同时 negative tests：缺少用法、重复 Taken、已停用、另一个 user、图像不可靠和 Provider timeout。

**Gate 4 · Minimum UI if time remains**
- 与已经真实存在的 API 连接，不允许前端假装有成功结果；手机竖屏主优先、横屏兼容、大字、可选语音、`[Taken] [Check pill] [Not now] [Unsure]`、单一患者界面。
- 如果仓库原本已有前端框架，不要无故覆盖或重写；按现有风格增量开发。未完成页面明确标识。

## 三、夜间停止/退化规则

1. 你可在**仓库内**修改源代码、运行 lint/test、添加可逆迁移、局部提交（如果环境允许且变更可审查），并持续下一个 P0 任务。不要擅自执行 `git push`、上线云服务或产生费用。
2. 未提供数据库 URL/LLM Key/Stage2 最新 schema：**仅阻塞对应 live integration**，改用注入的 fake adapter 和 fixture，写明 `SIMULATED`；其他模块继续。
3. 未确认许可证、真实患者数据、医疗建议、破坏现有合同、重大跨组件依赖：**暂停该分支**并在 `status/BLOCKERS.md` 记录；不可自作主张放开限制。
4. 不要安装无关包、不下载巨大模型/数据集、不在根目录产生几十个一次性脚本、不启动无限服务或 `npm install` 死循环。可运行你明确能完成的本地测试。
5. 每完成 Gate 要写 `status/WORK_LOG.md`: 具体改动文件、公共接口、单测/集成测试命令与**真实结果**、失败原因、known limitations、下一步；同步 `status/tasks.json` 只将通过验证的项标 `done`。
6. 如果 Craft 需要你未经授予的用户点击/授权，无法自动执行时应停在安全边界；将阻塞原因和继续操作写清楚。不要持续等待、不要假装成功。

## 四、最终交付格式（早晨醒来我能直接核对）

**01. Summary:** 哪些功能真实完成，哪些只是 mock/设计；严格区分 VERIFIED/SIMULATED/BLOCKED。  
**02. Component map:** 列公开 API/Ports/DTO 和依赖图，确保低耦合高内聚。  
**03. Changed files:** 逐一列出文件及理由，禁止无意义大规模重构。  
**04. Tests:** 命令、通过/失败数量、外部环境是否实际连接。  
**05. Safety:** 已验证和未验证的保护规则。  
**06. Next 3 tasks:** 按 P0/P1、依赖和截止时间排序。  
**07. Evidence:** 哪些真实 WorkBuddy 会话需要截图，以及可对应的代码 diff/测试日志。  
**08. Git:** 工作区状态与本地 commit hash（如有，需是英文），不得声称已 push。

现在就开始，遵守所有强制工程约束，不要陷入纯讨论，尽量完成一个**真实可运行且可测试的纵向切片**，而非只有架构空文件。
