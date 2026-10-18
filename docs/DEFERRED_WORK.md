# MediThread — Deferred Work & Approval Gates

## UX Polish C.1 — local Workspace acceptance (2026-10-18)

- Owner now explicitly approved desktop history default-open and retention after selection, bottom quick-task/composer grouping, natural-width messages and multiline composer. This supersedes the reconciliation's MS-03 uncertainty for **current** behavior, without reconstructing an earlier approval. Register MT-CHAT-06/13–16 tracks the separate behaviors.
- Local implementation only: existing AssistantScreen/shared ConversationSurface/history browser and scoped CSS; no Agent, Conversation API/DTO, schema,026 or backend change. C and C.1 remain uncommitted/unpushed/undeployed by this work; production Live SHA not probed. Attached reference board is not runtime proof; actual local App screenshots are outputs/ux-c1/workspace-*.
- PASS local:44 focused frontend tests; actual App→localhost FastAPI/DEMO memory browser1test covers28width/language/font combinations, default/retained desktop history, toggle width, independent A/B drafts, short bubbles, bottom8–12px gap, long word/CJK/multi-turn timeline, mobile history selection, photo preview and real legacy read-only contract. Separate BUG01 EN/ZH photo-send/history browser1test passed using mocked provider/HTTP. Typecheck/lint/build/strict changed-E2E TypeScript passed. No database/provider regression rerun or production/physical device claim.
- Existing backend BUG-04–09, durable attachment/consent/audit deletion and all production gates remain unchanged. Source/tool explanation reuses existing actual response fields, no fabricated sources/parameters/reasoning or new tool/streaming API. Detailed scope and checks: status/UX_POLISH_C1_20261018.md.

## Requirement reconciliation — 2026-10-18 (evidence-only audit)

The original entries/IDs/background and approval gates below are retained. Behavior-level current scope/evidence is indexed in [REQUIREMENTS](REQUIREMENTS.md), gaps and proposed execution order in [REQUIREMENT_GAPS](REQUIREMENT_GAPS.md), continuing engineering acceptance in [REQUIREMENT_ACCEPTANCE](REQUIREMENT_ACCEPTANCE.md). These are not a second backlog or development permission.

- **BUG-04/05/06/08 remain open**: reran only `tests/backend/agent_patient_semantics_audit.py` on current working tree:30cases,10passed/20failed; output `outputs/requirements-agent-audit-20261018.xml`. Past-date confirmation proposal, yesterday/current-plan read, overlap audit allowlist, patient-readable current/history/status, follow-up local date and health-note completeness still fail. No confirmation or production/provider request was performed. General regression totals do not close these behaviors.
- **BUG-07 update, scoped**: the previously failing long-Chinese context test now passes on current shared bounded-context implementation. This plus UX C's existing SQL/restore evidence supports local budget repair, not all historical session shapes, production rollout or closure of BUG-04–09. Old21failure report is historical; current20failure result supersedes only this test's status.
- **BUG-09 remains open**: existing openFDA tool and choice continuation do not satisfy the reported Amlodipine general-use answer; actual provider/new-runtime acceptance is still missing. No knowledge matching or renderer fix this round.
- **AG-06 remains PARTIAL for approved attachment behavior**: durable threads/continuation are locally verified; stored chat attachment metadata is presence-only, without durable original-image/reference restoration. Current desktop history starts closed and selection closes it; whether default/selection persistence was previously required lacks an accessible explicit source (MS-03), so no new UI defect or implicit implementation authorization is inferred. Production026 evidence is historical and does not verify current application deployment or live Gemini.
- **DB-06 remains PARTIAL/BLOCKED**: pure-draft027 SQL slice exists and was tested previously, but immutable audit-linked graphs are refused; `audit_events` references are not deleted or rewritten. Typical audited create→delete needs a separately approved retention/reference design. Storage cleanup has durable receipts/current-page retry but no reload-surviving pending-cleanup list. No production027, rollback or live Storage execution in this audit.
- **REC-01 clarification retained**: latest owner required equal-name browsing; that is locally implemented. Do not reopen the obsolete top-level independent-registration labels or make authoritative ingredient mapping a prerequisite for browsing. Trusted ingredient aggregation is a separate proposal/requirement decision, not authorization to add schema or merge records. New Supabase read-query/paging acceptance remains unverified.
- **AUTH-01 / DB-04 / AG-02 / OPS-01/02**: code/old evidence boundaries unchanged. Real guest/email upgrade and patient/Storage retention remain unverified; enrollment initial-stock integration is not implemented; local photo-consent revocation is not proof of cross-device or remote deletion; one-shot processed0 is not device receipt and last-knownCron0 is not current monitoring. Keep independent approval gates.
- **Documentation conflicts only**: BUG-01's early uncommitted wording is superseded by later local commit `1ea994b`; no production-history impact assessment or deployment proof inferred. Old task-table/status/preflight claims are dated, not current completion percentages. No old files or ignore rules were cleaned.

This round changes documentation/rules only. No business feature, API, schema, migration, auth, inventory, model or production behavior changed. Next recommendations are limited to the three evidence-backed candidates at the end of REQUIREMENT_GAPS; all still require concrete owner authorization.

**整理／核对日期：2026-10-17；本地代码基线：`abd24c9`。**  
**性质：待办及审批清单，不是实现授权或生产变更指令。**

本文件是后续持续维护的台账。原始输入 `MediThread_Deferred_Work_Backlog_2026-10-17.md` 保留不变，作为历史背景，不作为第二份持续更新台账。原始条目的风险与批准条件继续有效；最新状态以本文“证据与当前状态”部分为准。只维护文档，不代表允许实现任何条目、清理仓库或修改 Git 索引。

> 来源为截至此日期的项目沟通和 Codex 提供的技术方案。凡未见到最终合并、测试和部署验收的功能，状态统一记为“待核查/未确认”，不假定仍未实现，也不假定已经完成。

## 一、批准原则

- **允许随时执行**：只读代码/Schema 审查、编写技术方案、在隔离的本地虚拟环境安装测试依赖、使用合成数据执行不写生产的测试。不得因此修改生产数据。
- **需要单独授权**：新增或修改后端写入行为、Auth 身份归属、数据库 Migration/RLS/Storage Policy、正式通知发送、Supabase Cron、生产 Secrets/Deploy。
- **Git 约束**：未经用户明确说“授权提交本轮改动”，不执行 `git add`、`git commit`、`--amend`、`merge`、`rebase`、`push`。不丢弃已有工作；可以修改工作区、运行测试与用只读 Git 命令检查。
- **验收顺序**：先核查当前实现 → 说明最小变更及数据影响 → 本地合成数据测试 → 用户批准相应实现 → 实施与回归 → 用户单独批准 Commit → 用户单独批准生产发布/SQL/Cron。
- **本清单中任一项“满足批准条件”不等于自动获得批准**；仍需用户逐项明确授权。
- **持续维护授权**：每轮开始阅读相关条目并排查重合；结束审查新缺陷、技术债务与未实现需求。仅依具体代码或测试证据新增／更新，保留 ID、历史背景、风险及审批条件。允许自行维护本文件，但变更必须留在未提交工作树；文档维护不等于开发授权。
- **证据分层**：分别记录本地代码实现、本地测试、线上部署、真实设备验收；任一层通过不能代替其他层。历史报告不能证明当前生产状态。
- **主动建议上限**：每轮最多推荐 1–3 项确实适合推进的任务，列出已满足／未验证条件、预计代码/API/数据库/权限范围、风险及建议。没有合适项目时无需推荐。
- **敏感变更**：数据库写入、Auth、RLS、剂量事件、库存审计、历史消息迁移及生产调度须先独立出方案并等待具体授权。Git／Deploy／生产 Secrets 权限仍单独审批。

## 二、后端 / 数据库 / 患者数据写入

| ID | 暂缓任务与当前已知状态 | 批准实现前的客观条件 | 建议时机 |
|---|---|---|---|
| DB-01 | **历史服药状态补记（Historical Dose Backfill）**。技术提案 `docs/DOSE_BACKFILL_PROPOSAL.md` 已完成；接口尚未实现。 | `pharmascan-care` 环境可运行相关 pytest；审清 `due_at`、实际自报 `event_time` 与服务端 `created_at`；仅允许已有、当前患者所有、未报告的历史 occurrence；确认挑战和幂等绑定；不覆盖既有记录；明确库存不得因补记意外重复扣减；合成数据测试通过。 | **核心 Agent / Demo 稳定后单独批准**。第一版建议只支持当前有效计划内已持久化的过期 occurrence，不扩展到历史已结束计划。 |
| DB-02 | **补记已结束 / 已替代 Regimen 的历史发生项**，与 DB-01 不应捆绑。当前写入保护只允许 active plans。 | 单独复核业务政策、数据库守卫、关联事件、跨版本/疗程归属、并发与审计；如需 Migration/RLS，先审查 SQL/回滚和隔离测试。 | DB-01 的受限版本通过后，再按实际用户需求决定是否批准。 |
| DB-03 | **补记后的纠错/修改既有服药报告**。现有接口禁止二次报告；未提出可用的安全纠错契约。 | 设计更正事件、来源、审计、冲突与依从性统计更新规则；不得覆盖或抹掉原报告。 | 未来独立功能；目前不批准。 |
| DB-04 | **首次登记药物时一并记录初始库存**。UI 诉求明确，但 Inventory API 是否支持安全联动未确认。 | 确认已有库存 DTO/API、库存单位、Unknown≠0、患者归属、同一登记重试幂等、计划激活与库存写入失败时如何处理；验证不重复扣减库存。 | 如果现有安全 API 支持，下一轮可单独申请；涉及 DB 迁移则再审查。 |
| AUTH-01 | **访客账户绑定邮箱、登录已有账户及患者数据保留**。UI 入口可先改，但完整身份升级/迁移能力仍需核验。 | 先证明 Supabase Anonymous→永久身份升级与 Sign-In 的真实实现和会话转换语义；不同账户医疗数据绝不自动合并；合成账户 A/B 测试 Auth、RLS、Storage 隔离与账号恢复。 | 账号演示前先做只读审查；仅验证安全时批准实现。 |
| DB-05 | **细分上传来源（药房标签 / 处方 / 药盒等）的可靠持久化**。如果已有来源字段，不属于待开发。 | 核查来源分类是否已存储且可追溯；不能凭图片外观猜测；如需新的 DTO/Migration，先审批。 | 先让 Codex 核查，能用已有字段展示则直接作为普通 UI 工作处理。 |

## 三、Agent / 医疗图像 / 工具交互

| ID | 暂缓任务与当前已知状态 | 批准条件 | 建议时机 |
|---|---|---|---|
| AG-01 | **照片类型自动建议或自动路由（药房标签、处方、包装、裸药片）**。不能假装分类准确；Stage1/Stage2/图库各路径的线上能力待实际追踪。 | 先做可重复的合成照片路由测试；展示模型置信、不确定/冲突及用户纠正；不把裸药片作为 OCR 文档、不自动确认身份或剂量。 | Phase 04 核查真实 Tool Calling 后决定最小实现。 |
| AG-02 | **照片处理授权减少重复勾选**。现有逐照片勾选增加摩擦，但不能默认为已同意。 | 核查授权覆盖范围、原图保留行为、分析前授权、已保存聊天派生内容和撤回入口；明确首次/单次/持续授权的产品和隐私语义。 | 独立隐私审查后批准；不和图像识别准确性混合。 |
| AG-03 | **动态药物选择 Structured UI Actions**。用户问“这个药”且含歧义时，显示当前患者真实药物选项；复数问题优先直接回答。 | Agent 当前药物查询与知识库工具准确性先通过；检查动态选项的权限绑定、同名不同规格及可继续会话；若需改 API 返回契约先审批。 | Phase 04 的基础路由、知识库/回答正确性通过后实施。 |
| AG-04 | **真实 Tool Execution Progress / SSE Streaming**。只显示真实开始、完成、失败事件；不能伪造工具调用。 | 审查现有 Tool Trace/流式能力；能复用则小范围加入；如需要整体 API Streaming 改造，应先评估成本。 | Agent 正确调用工具、回答有证据之后；非 Demo 阻断时可后置。 |
| AG-05 | **中文和其他语种的语音 ASR/TTS 扩展**。既往测试英文浏览器 ASR 可用、中文曾不可用，现状待复测。 | 明确当前生产浏览器与移动端语音支持及真实兼容范围、隐私/成本；不伪称支持。 | 只有目标演示语种不可用时再单独批准。 |

> **不应延期处理的真实缺陷**：工具未调用/图像候选未经过安全整理、回答与患者真实数据不符、内部 Tool Prompt/原始 JSON 被显示或保存为患者消息、跨患者访问问题。发现这些应进入当前 P0 故障修复，而非上述可选功能排期。

## 四、前端 / 聊天历史 / 长期照护体验

| ID | 暂缓任务 | 批准条件 | 建议时机 |
|---|---|---|---|
| UX-01 | **按需生成每日照护总结并可查看历史**，与普通聊天摘要分离。 | 先验证本周总结的时间范围、计划版本、记录来源、未报告含义正确；明确哪些来自患者自报，哪些只是讨论；生成/缓存/失效/隐私授权有设计。 | Phase 04 本周总结准确后，再独立批准。 |
| UX-02 | **单轮问答或逐条消息删除**。删除聊天不等于撤销已执行的用药/跟进操作。 | 梳理会话/工具调用引用、删除后模型上下文、保存记录、审计保留与衍生摘要失效；删除语义对用户透明。 | 低优先级，当前暂缓。优先保证整个已保存会话的管理能力正确。 |
| UX-03 | **更高级的固定三栏 Assistant 上下文预览 / 全面会话搜索**。已有完整 Assistant Workspace，可用可折叠侧栏避免挤压输入。 | 先验证当前工作区导航、历史恢复和工具结果；如用户测试确有需求再做。 | 非当前必需；避免额外复杂度。 |

## 五、生产运营 / 推送与发布（单独授权）

| ID | 待验收任务 | 批准前条件 | 建议时机 |
|---|---|---|---|
| OPS-01 | **受控的一次性 Dispatcher 调度 / 真机收到通知**。已知有生产订阅启用，曾核查队列为 0；本清单无法确认最新一轮真实调度是否已执行。 | Codex 先重新只读检查现有 Cron/任务状态、来源版本、测试账户和所有当前可发送任务的患者范围；用户另行授权一次签名调用；真实设备收到并可点击后记录证据。 | 在启用 Cron 前；不将早前“范围安全”结果当成永久有效。 |
| OPS-02 | **Supabase pg_cron 每分钟自动触发 Dispatcher**。`pg_net` 和 Vault secret 曾配置，但不等于 Cron 已启用。 | OPS-01 成功并实测错误/重复发送保护、生产影响范围、监控和停用方式；用户明确授权 SQL 和自动化启用。 | 完成真实设备验收后。 |
| OPS-03 | **生产 Release Audit / Git 推送合并与演示验收**。代码的本地 Commit/单测通过不等于已部署。 | 核对当前 branch、未提交/未推送差异、迁移摘要、Vercel/Render/Worker 实际 Live SHA、匿名与已登录 E2E、隐私与药物关键路径；单独申请 Git/Deploy 权限。 | 每次拟上线前执行。 |

## 六、已知不应再当成旧阻断项自动重做

- Supabase Migration `025` 已有记录表明曾应用且迁移哈希匹配；旧的 001–024 不应重跑。迁移状态要以**当前只读核查**为准，不按旧 WorkBuddy 阶段计划重建。
- 患者 API Web Push 配置曾返回 `available=true`、`test_available=false`；后者是独立 Dispatcher 架构下预期设计，不应要求把 VAPID 私钥放回患者 API。
- Logo、待核对计数与草稿取消等此前已完成本地修复；只有实际回归失败才重新打开。

## 七、交给 Codex 的后续指令模板

> 请读取 `docs/DEFERRED_WORK.md`，这是**待办审查与授权台账**，不是本轮开发授权。先做只读现状核验，按 ID 返回：已经完成 / 部分完成 / 未实现 / 被其他工作阻断、需要修改哪些文件/API/Schema、风险、先决测试以及是否需要数据库或生产操作。不要执行任何暂缓项、不要修改生产数据或配置。对建议解锁的项目逐项提出最小范围与回滚方案，等待我明确批准某个 ID 才能修改。未经我另行批准，不执行 `git add`、Commit、Merge、Push 或 Deploy。

**维护入口**：后续只持续更新 `docs/DEFERRED_WORK.md`。2026-10-17 用户已授权建立与维护台账，但未授权提交、实现暂缓任务或执行旧文件清理。

## 八、已确认缺陷：BUG-01 / P0 — 照片技术上下文进入聊天历史

**状态：已确认的 P0 缺陷；2026-10-17 已获准本地修复，当前未提交工作树已实现分离并通过定向验证。未部署，生产及旧历史影响未验，不标记为全面关闭。**

### 具体证据（修复前基线 `abd24c9`，保留定位背景）

- 前端 [`AssistantScreen.send`](../frontend/src/components/AssistantScreen.tsx)（基线约 112–115 行）把患者 `question`、附件处理结果 `JSON.stringify(evidence)` 及内部限制说明拼成 `messageText`，通过 `api.sendMessage({text: messageText, ...})` 发送。当前即时展示使用单独的 `question`，不能证明保存内容也干净。
- 后端 [`agent.send_message`](../backend/app/transport/routes/agent.py)（约 79、88–92 行）将 `payload.text` 交给 orchestrator；聊天保存开启时，又把同一 `payload.text` 传给 `conversation_history.append`。
- [`ConversationHistoryService.append`](../backend/app/application/conversation_history.py) 将该文本写为 `user_text`；[`bounded_text`](../backend/app/contracts/privacy.py) 执行密钥样式脱敏和长度截断，但不分离患者原话与技术上下文。
- [`ConversationHistoryBrowser`](../frontend/src/components/ConversationHistoryBrowser.tsx) 从 `user_text` 生成历史标题；[`AssistantScreen`](../frontend/src/components/AssistantScreen.tsx) 的历史详情直接显示 `selectedHistory.user_text`。因此存在技术说明／JSON 以患者消息保存及回显的确定代码路径。未据此推定当前生产已有多少受影响记录。

### 目标与仍需核查范围

1. 患者原话、附件证据、内部工具上下文应明确分离。患者可读历史仅保存／显示真实患者表达及经明确设计的附件说明；工具证据保留类型、来源、归属及不可信数据边界，不能伪装成患者指令。
2. 是否污染**后续** LLM 上下文仍需沿 orchestrator、session/recent turns、模型输入构建路径核查。当前已确认混合文本进入当次 orchestrator；这不等于已证明跨轮污染机制或模型行为。
3. 历史已保存数据的影响范围、线上版本与实际发生情况仍需只读核查。不得输出患者原文、图片内容、JWT 或 Secrets；优先采用不暴露正文的范围统计方案。
4. 分离是否需要调整 `AgentMessageRequest`、类型化附件引用及服务端验证，先提供最小独立方案；不要仅在显示层裁剪 JSON 掩盖保存问题。

### 风险、依赖与批准条件

- 风险：高，涉及消息真实性、隐私边界、提示注入防护和会话上下文；属于缺陷修复优先级，不作为普通低优先级功能排期。
- 依赖：关联 AG-01（图片路由）、AG-02（授权／派生内容保存）、AG-06（历史与会话恢复）及 UX-02（删除语义）。AG-06、逐条删除或复杂搜索不应成为修复 BUG-01 的前置开发。
- 先决测试：无图／有图、保存开／关、即时显示与刷新后历史、重复发送、来源归属、跨患者拒绝、恶意附件文本、既有 Tool Calling／确认流程不回归；使用隔离合成数据。
- **未经具体授权，不实施修复。不得擅自删除、迁移、重写或覆盖生产历史记录；新写入路径修复与历史数据处置必须分别审批。** 不借此改 Auth/RLS、医疗记录、库存或生产配置。
- 解除门槛：最小数据分离方案及上下文／历史影响审查完成，用户批准明确代码/API范围；生产验收与任何历史数据操作另行批准。

### 本地修复记录（2026-10-17，尚未提交）

- 用户已授权本地 BUG-01 代码与测试，未授权 Git Stage/Commit、部署或生产历史处置。上文“本次仅记录／等待本地实现”门槛已由这次明确授权更新；所有生产与敏感数据门槛继续有效。
- `AgentMessageRequest` 增加可选、受限的 `photo_context`；旧纯文字请求兼容，响应与数据库结构不变。`AssistantScreen` 经既有图片接口取得结果后，用类型化投影传证据，`text` 仅为患者原话，不再拼 JSON／内部说明。
- [`ChatPhotoContext`](../backend/app/contracts/chat_photo.py) 固定信任标签：客户端中继、未经确认、不是患者陈述、不能授权写入。原图上传／同意路径不变，不将客户端中继数据冒充服务端已认证来源。
- `ConversationService` 当轮模型输入单独包含该证据，`current_input` 保持原话；`AgentTurn.patient_text` 仅添加固定的本地化附件提示，供现有历史与最近轮次使用。完整技术证据不保存在用户文本或未来轮次的用户上下文中。
- 模型侧只提供照片回合的只读工具，`ModelTools.execute` 再独立拒绝非只读工具；不能由 OCR 推导服药／健康／库存写入意图。需要写入时应通过单独明确文字请求及原有确认流程，不借照片证据创建受信患者引用。
- 客户端的药房标签、药盒、处方、裸药片及不明确图片路径继续复用原有接口；确认、语音、历史回看相关测试纳入定向回归。所有测试使用合成资料与模拟提供方，未声称真实模型／生产验收。
- 后续 LLM 上下文风险已在本地两轮模型测试核查：修复前混合文本经 `record_context` 进入 `recent_turns` 后会再次进入模型的 `context`；修复后技术字段仅在当轮 `untrusted_photo_evidence`，下一轮不带该原始证据。允许的患者可读、明确未确认的助手说明仍属于正常对话，不是新的医疗事实。
- 旧生产记录**可能仍含混合文本**；本轮没有读取或统计其实际范围，没有做正则隐藏、清洗、迁移、删除或覆盖。历史存量处置仍需独立方案／批准。
- 发布顺序：后端兼容扩展在前，前端在后。旧后端不认识新字段会拒绝；旧前端在升级前仍会发送旧混合文本。此次本地通过不等于线上 BUG-01 已解除。
- 本轮实际验证：后端 7 个相关文件共 91 passed（其中新边界文件 26 项）；前端 5 个文件共 43 passed；真实 Chrome 浏览器／模拟 HTTP 的两个场景 2 passed，覆盖 EN/ZH 新消息和历史显示及原有图片流程。Ruff/check+format、Typecheck、ESLint、Build、diff 检查通过；保留既有 Starlette 弃用与 Vite 分包提示。没有真实 Stage2/Gemini 或生产数据库验收。
- 复现与兼容契约见 [API_CONTRACTS](API_CONTRACTS.md#patient-message--photo-evidence-boundary-bug-01)。

## 九、AG-06 — 历史会话回看与 Agent Session 恢复边界

**原审查状态（实施前，保留背景）：历史回看已在本地实现；完整旧 Agent Session 恢复未验证，公开历史契约不足；当时未授权新增恢复功能。**

**2026-10-18 UX Polish C：本轮已获得稳定 Conversation、必要 API/模型及兼容生产迁移的具体授权。** 新实现通过 `ConversationThreadService`、`ConversationThreads` 公共端口和既有 `conversation_turns` 存储文本；新增独立身份，不按日期回填旧问答。026 已完成目标生产 Schema 迁移及目录核验，前后端未由本轮发布。旧问答继续只读；新 Conversation 可恢复有界语境并续聊，不能宣称恢复完整旧 Agent Session、Tool Trace 或有效写入确认。

- 本地证据：[`test_conversation_threads.py`](../tests/backend/test_conversation_threads.py)、[`test_conversation_threads_sql.py`](../tests/backend/test_conversation_threads_sql.py)、[`conversation-threads.spec.ts`](../frontend/e2e/conversation-threads.spec.ts)。真实隔离 PostgreSQL 验证 RLS、竞争请求、旧记录保留及空表回退；实际浏览器通过真实 HTTP/SQL 验证 A/B、刷新、草稿和续聊。模型为显式 DEMO 无状态适配器，不能据此宣称真实 Gemini 验收完成。
- 安全边界：保存关闭不新增持久化 Conversation/问答/请求占位；临时运行上下文延续现有机制，不能承诺物理定时擦除或跨设备恢复。恢复最多六段、总 UTF-8 预算 16KB 的不可信文本；不恢复执行状态，必要事实重新经工具查询。历史图片仅保留附件存在标记，原件与旧工具状态没有被伪造为可恢复附件。
- 发布依赖：026 → 兼容后端 → 前端；真实 Provider、线上 JWT/账户和手机键盘/语音验收仍待验证。生产后续已出现非测试患者的新会话活动，不读取其正文、不回填、不清洗；仅空数据的回退方案必须拒绝有数据时执行，届时优先前向修复。
- 后续范围门槛保留：历史批量迁移、完整 Provider Session/Tool 状态恢复、附件持久化或新的保留/删除策略不因本轮自动获授权。接口与部署边界见 [`CONVERSATIONS.md`](CONVERSATIONS.md)。

### 已有真实能力与证据

- [`HistoryEntry` / `HistoryPage`](../backend/app/contracts/conversation_history.py) 向患者公开已保存问答的 `id`、`user_text`、`assistant_text`、`created_at` 及分页游标。真实范围仅限当前授权患者允许保留、且接口实际返回的条目，不是所有历史健康或工具记录。
- [`ConversationHistoryService.page`](../backend/app/application/conversation_history.py) 读取最近 30 天内的授权条目，每页最多 20 条，受既有保留策略约束；[`ConversationHistoryBrowser`](../frontend/src/components/ConversationHistoryBrowser.tsx) 使用患者时区分组并加载真实问答；[`AssistantScreen`](../frontend/src/components/AssistantScreen.tsx) 选择历史项后展示该问答，可返回当前对话。公开历史条目不是附件原件、完整工具状态或医疗业务记录的恢复接口。
- 保存开关与清除确认延续既有实现；未开启保存不能伪造持久化历史。已保存问答的 ID 不等于 Agent Session ID，同日多个条目不等于同一个会话。

### 具体限制

- **内部 `HistoryTurn` 已有 `session_id`**；缺少的是公开 `HistoryEntry` 中供恢复使用的授权 session 标识／契约，不能误写成数据库根本没有 Session ID。
- 当前历史选择仅设置 `selectedHistory`，没有证明会加载该旧 Session 的 orchestrator 状态、上下文版本、工具结果关联或有效确认挑战。
- 当前会话／最近轮次读取能力与“从任意已保存历史恢复完整 Agent Session”必须区分；历史问答不替代当前授权医疗事实，也不能复用已过期／已消费的写入确认。
- 不得把“历史可回看”宣称为“完整会话已恢复”。是否需要新会话模型尚未决定：先核实既有 session、有效期与读取接口能否满足需求，不默认新增表。

### 风险、依赖与批准条件

- 风险：中高；如果涉及恢复工具状态或可写确认，提升为高风险并单独评审。必须保持患者隔离、未发送草稿和当前会话。
- 依赖 BUG-01 的消息／证据边界；关联 UX-02 删除与上下文失效、UX-03 搜索；无需为回看功能强制实现复杂搜索或新会话数据库。
- 先明确患者需求、只读回看与继续新会话／恢复旧 Session 的差异，再评估 DTO/API、过期策略、工具状态和隐私影响；以合成 A/B 患者验证权限、过期、切换、草稿和新建会话不覆盖旧保存内容。
- 当前只授权审查与台账维护；**不新增 Session API、数据库结构或复杂历史恢复功能**。任何敏感状态恢复、迁移或生产验收须另行批准。

## 十、证据与当前状态（2026-10-17，本地基线 `abd24c9`）

以下为代码审查与此前实际本地测试的状态补充，保留上文原始批准条件；不是本轮重新运行全部测试，也不证明生产部署或真机验收。

| ID | 已核实的本地状态／证据 | 尚未满足的门槛 |
|---|---|---|
| DB-01 | 提案存在；既有确认／剂量基础可测试。`pharmascan-care` 正确解释器已找到，剂量／确认／长期照护定向测试 73 passed。 | 专门补记功能未实现；时间、库存归属、审计方案及实现授权仍缺。测试环境就绪不等于补记已获批准。 |
| DB-02 | [`policy.check_dose_write_preconditions`](../backend/app/domain/policy.py) 及 SQL 守卫限制 active 计划。 | 历史计划放行方案、数据库约束评审与明确授权。 |
| DB-03 | 既有发生项二次报告被拒绝，原始记录不可直接覆盖。 | 更正／审计契约尚未设计与授权。 |
| DB-04 | [`InventoryPanel`](../frontend/src/components/InventoryPanel.tsx)、[`LongTermCareService`](../backend/app/application/long_term.py) 已有独立库存能力。 | 登记时联动、部分失败与重复提交规则未实现／验证；仍需写入授权。 |
| AUTH-01 | [`accountAuth`](../frontend/src/api/auth.ts) 已有 `updateUser` 绑定邮箱及 OTP／密码登录；相应本地模拟测试已有。 | 实际 Anonymous 升级与 A/B 身份、Storage/RLS 和数据保留验收；不授权数据自动合并或迁移。 |
| DB-05 | [`evidence_enrollment`](../backend/app/application/evidence_enrollment.py) 已将来源类型写入来源记录，自动建议与人工选择仍需区分。 | 已有字段无需重复开发；分类准确性和生产追溯仍需验收，未批准新 Schema。 |
| AG-01 | 图片检查、分流、来源读取及人工纠正路径已有；相关本地模拟测试存在。 | 模型准确性、完整线上路由与异常路径未完成验收。 |
| AG-02 | [`useImageConsent`](../frontend/src/imageConsent.ts) 按 owner 在设备本地保存显式许可，设置可撤回。 | 跨设备和派生聊天内容隐私审查仍缺，尤其受 BUG-01 影响；不得默认授权。 |
| AG-03 | 既有 Agent 有澄清状态／候选。 | 患者可操作的动态结构化药物选项尚未实现；API范围需先评审。 |
| AG-04 | `AssistantScreen` 可显示已返回的 Tool Trace。 | 实时开始／完成／失败事件、SSE 未实现；不能将最终 Trace 叫实时进度。 |
| AG-05 | 中文 `zh-CN` 识别配置／朗读路径和本地模拟测试已有。 | 真实浏览器／手机中文及其他语言兼容性未验，不据模拟测试声称真机支持。 |
| AG-06 | 见第九节；新 Conversation 本地续聊及 026 生产 Schema 已验证。 | 应用发布、真实 Provider/设备验收待做；不恢复旧确认或宣称完整 Session 恢复。 |
| UX-01 | 既有总结是 week/month/course（course 实际选择单一计划 ID）。 | 每日照护总结与历史生成／失效功能未实现；先验证既有总结范围。 |
| UX-02 | [`agent.clear_history`](../backend/app/transport/routes/agent.py) 有确认后的整批清除。 | 单轮／逐条删除未实现，不能把整批清除当作逐条管理。 |
| UX-03 | 完整工作区、可切换历史导航已有。 | 固定三栏当前非必需；全面搜索未实现，需先证明实际价值。 |
| OPS-01 | 历史获批一次性运行记录为 HTTP 200、processed=0。 | 不是设备送达证据；当前队列／订阅／版本和影响范围必须重新只读核查，正式发送另批。 |
| OPS-02 | [`push-cron.sql`](../deploy/dispatcher/push-cron.sql) 已有准备模板。 | 当前生产启用状态本轮未核查；先完成真机／重复保护验收，启用须明确授权。 |
| OPS-03 | 发布文档和本地测试已有；本地分支领先其远端引用 6 个提交。 | 不是实时 GitHub／生产版本证明；Live SHA、上线 E2E 与发布授权仍缺。 |
| BUG-01 | 第八节保留修复前证据；当前本地未提交修复已分离文字／证据，相关本地测试通过。 | 生产版本、真实模型路径与旧历史范围未验；Git／发布／旧数据处置仍分别授权。 |

**已有本地测试证据**：此前本地 73 项后端测试通过（剂量、确认、长期照护）；随后只读审查运行的 Auth／来源预览后端测试 22 passed，以及 Auth／MedicationEvidence／VoiceInput 前端测试 35 passed。均为本地／模拟，不能替代线上 Auth/RLS、真实模型、设备语音或推送送达验收。

### 本轮适合推进的建议（建议不等于授权）

- **BUG-01：建议下一步审查本地修复与只读生产影响核查方案。** 本地分离、当轮模型边界、后续上下文、只读工具保护和基础测试已就绪；没有数据库迁移。尚缺生产 Live 版本／真实模型及旧历史范围证据。预计是变更审查与获准的只读聚合核查，不需要历史数据写入；隐私风险高，不输出消息正文。Git／部署及任何存量处置仍单独授权。
- **DB-05：不建议重复开发来源持久化。** 相关字段与保存路径已存在；保留分类可靠性和生产追溯验收即可。若仅做只读核查，不需要新增 API／数据库／权限；分类真机与线上验证仍须分开记录。


## UX Polish A local review ? 2026-10-17

- Repository inspection now shows BUG-01 committed locally as `1ea994b`; this supersedes the earlier uncommitted description, without asserting deployment or production-history remediation. Its source and tests remain unchanged by UX Polish A.
- Presentation-only refinement: Me navigation hints, explicit Records grid ownership, Medicines medium-width shortcut span, readable form width and accessible required/optional labels. Summary actions remain separate existing routes; no segmented-control semantic change.
- Local validation results are recorded in this round's handoff. No new backend/API/schema work, no staging, commit, push or deployment. No new evidence-backed deferred defect identified in this limited scope.

- UX Polish A verification: TypeScript, ESLint, production build and diff checks passed; focused Vitest 21 passed; new browser grid/form checks 2 passed (form selector corrected to accessible role), existing related browser regression 5 passed. Synthetic authenticated HTTP only; seven widths 390?1920, EN/ZH and 100%/150% application text covered. Existing >500 kB bundle warning remains.

## BUG-02 — Current-medication education clarifies before discovering owned records

- Evidence: `ConversationService` previously allowed `clarify_medication_care` before an owned active-medication read; `get_medication_understanding` used an existing session reference but did not discover a unique current medication. The owner explicitly authorized the local orchestration fix; this is separate from AG-06 full session restoration.
- Ownership/interfaces: Agent-only read planning through existing `ModelTools.execute`, `list_active_medications` and `get_medication_understanding`. No HTTP DTO, dependency, schema, RLS, dose/inventory or database write change.
- Local behavior: recognized contextual EN/ZH use questions first list current owned plans; one unambiguous match continues to sourced education. Multiple matches show actual names; a verified active reference narrows selection. A stale reference cannot silently switch medicines. Explicit plural questions read at most three medicines, preserving the existing four-tool budget; larger lists require explicit batching. Photo turns retain their separate evidence path.
- Acceptance: real application/repository synthetic tests cover unique/multiple/empty/draft/other-owner/stale references, plural bounds and unavailable providers. Named-drug, dose-change and unrelated requests remain outside this narrow deterministic read planner. Model-based general phrasing retains the existing orchestration with improved discovery instructions.
- Rollback: remove the isolated planner and its ConversationService entry/instruction changes; no data rollback or migration is required. Production deployment, real Gemini traces and the reported user's exact runtime remain unverified; no Git or deployment action is authorized by this entry.
- Validation: six focused backend suites, 176 passed; Ruff lint/format and diff checks passed. Existing Starlette deprecation warning retained. Local synthetic application/tool integration only; no external provider calls or production writes.
- Owner follow-up confirmed the screenshots are from production while this fix is still uncommitted. Production behavior is not evidence that the local planner ran. No production repair/deployment is claimed.
- Follow-up evidence: education uses the shared `get_long_term_care` audit category with an existing `payload.action`; a grouped success cannot establish which action ran. The old frontend also labeled every non-Gemini response an AI outage, and `medication_fallback` collapsed every DomainError into a request for the medication name. Local follow-up now labels the known action, adds `records_only` provenance, preserves safe failure codes and lets authentication failures propagate. The exact production lookup failure remains unverified until a current runtime trace is available; no secret or patient-content logging added.
- Follow-up validation: 181 backend tests and 19 focused frontend tests passed; TypeScript, ESLint, Vite production build, Ruff lint/format and diff checks passed. Existing Starlette and bundle-size warnings remain. Exact named Chinese query `Nifedipine LA有什么作用` covered with synthetic provider results/errors. No production provider calls, database changes, Git staging/commit or deployment.
- Subsequent owner correction: the latest list-only/default-Chinese-reply screenshot is local, not production. Read-only runtime inspection found both local frontend proxies reaching port 8001; its Uvicorn process started at 15:59 on 2026-10-17, has no `--reload`, and predates the 21:28 planner/conversation files. `scripts/start_dev.py` likewise omits reload. The current source recognizes the exact question; focused contextual tests reran with 21 passed / 46 deselected. Restarting the intended local development server is required before browser acceptance; the existing process was not terminated and no authenticated chat/database writes were made during diagnosis. Commit `f664c5b` is now present locally; runtime reload and production deployment remain distinct from source availability.
- Owner-authorized development-only follow-up: `start_dev.py` now defaults to watching `backend/app/*.py` recursively, with `--no-reload` override. The launcher replaces only its own API process, including after a Python error; Vite remains running. Actual Windows smoke showed Uvicorn's native CTRL_C_EVENT reload stall with hidden/redirected console I/O, so the implementation uses the existing launcher process cleanup/restart mechanism and no new dependencies. Environment/dependency/launcher changes still require a manual restart. Render/Dispatcher startup and all clinical/auth/database behavior are untouched. Independent synthetic HTTP smoke confirmed before/after code versions and cleanup; existing user servers were not stopped. Changes remain uncommitted.
- Further BUG-02 local defect: the initial discovery fix listed choices but did not retain the education task, so a following bare `Nifedipine LA` or `Amlodipine` lost the original use question. Local follow-up reuses existing `AgentContext.active_task` string markers (no new context/HTTP fields or schema) to recognize education selections. Each turn rereads the current patient's active list; only a unique exact/name-prefix match establishes the existing medication/regimen references. Case/spacing normalization does not equate different strengths or formulations. Multiple matches clarify; unmatched or unrelated input follows normal routing. Selected replies include the actual recorded name, and another known medicine can continue the education task. Existing session JSON roundtrip is covered; this is not AG-06 full saved-session restoration.
- Choice-continuation acceptance: EN/ZH question → choices → `Nifedipine LA` resolves `Nifedipine LA 30 mg` → `Amlodipine` switches to that owned medicine; strength ambiguity/instruction text and unrelated-topic routing covered. Six focused backend suites: 190 passed; Ruff lint/format and diff checks passed. Synthetic/local only; no actual patient writes, model/provider calls, frontend changes or deployment. Previous development-reload changes are preserved and remain a separate review/commit scope.
- Open local acceptance blocker: owner reported the generic ErrorNotice popup after selecting `Nifedipine LA`. `ErrorNotice` maps most ApiError messages to the same patient-safe text, so the screenshot does not identify HTTP status or error code. Added two synthetic real-DTO label regressions (printed instructions/product form, ER release and checked/unchecked DoseBasis); both passed without reproducing the popup. Actual failed `/api/agent/messages` status/code/message/rule_id are requested; no JWT, request body or production data needed. Do not mark this browser failure resolved or alter schema/permissions based on guesses. No business-code change in this diagnostic follow-up.

## BUG-03 / P1 — Medication-education audit violates the database state contract

- Owner supplied the safe error envelope: `INVALID_INPUT`, `Supabase rejected data operation (HTTP 400; code 23514)`, no rule ID. This is a database CHECK rejection, not proof of a Gemini failure.
- Confirmed code defect: `ModelTools.execute(get_medication_understanding)` included `state=medication_understanding`. `ToolRegistry` copied that state into the redacted trace summary. Migration 002's `core_trace_summary_is_safe` permits only lifecycle states; `agent_tool_calls.response_summary` applies that function as a CHECK. Existing memory trace storage did not enforce it.
- Local reproduction: the real SupabaseDataClient and trace repository against synthetic HTTP enforcing the exact state allowlist extracted from migration 002 reproduced the same HTTP 400/23514 before the patch. This is a local contract simulation, not a live SQL execution.
- Minimal local fix: remove the action label from `state`; keep the existing `action=get_medication_understanding`, audit category, item count, status, patient scope and full audit write. No fabricated lifecycle value, swallowed audit failure, schema/migration/RLS change or patient-data cleanup. Rollback is the one payload-field removal, but would reintroduce the known constraint failure.
- Validation: reproduction now passes and explicitly still rejects the old invalid state; all three expected discovery/education audit writes remain present. Six focused backend suites: 193 passed; related frontend provenance/photo tests: 9 passed; Ruff lint/format and diff checks passed. Existing Starlette warning remains. Local-only, uncommitted; the owner's actual browser retry and production deployment remain unverified. Review this fix separately from the pending conversation-continuation and development-reload changes.

## Patient-answer audit — 2026-10-17

Local synthetic acceptance only: existing regression 272 passed; explicit `tests/backend/agent_patient_semantics_audit.py` 30 cases, 9 passed / 21 failed. Failing acceptance is not release verification. No live Gemini, production SQL or new business implementation. Detailed local evidence: `outputs/AGENT_PATIENT_AUDIT_2026-10-17.md` and JUnit outputs. Earlier UX Polish A's historical-backfill reference should read DB-01/DB-02, not DB-05; original entry IDs and approval gates remain unchanged.

### BUG-04 / P0 — Past-date statement can prepare a current-day confirmation

- Controlled `ModelTools.prepare_self_report` with “I took Amlodipine yesterday” prepares today's occurrence. No confirmation was submitted and no dose event written; real Gemini tool selection is unverified.
- Existing confirmation UI does not by itself prove the proposed date matches the patient's statement. Review date guard and patient-visible proposal semantics before implementation. Depends on DB-01/DB-02 boundaries; this finding does not authorize historical writes, inventory changes, migration or ended-plan writes.

### BUG-05 / P1 — Yesterday reads ignore requested date and historical plan ownership

- `registry._get_dose_status` accepts but ignores day_offset; model_tools.Status omits it; orchestrator planning and rendering favor today. Opposite today/yesterday synthetic statuses fail direct and natural-language tests.
- Replaced-plan test preserves old event via explicit old-ID history, but date-status lookup selects new current version. Do not rewrite records or equate plan versions with courses. Read-contract/date/version repair requires an explicit task; schema needs must be assessed first.

### BUG-06 / P1 — Overlap rejection cannot satisfy audit error-code allowlist

- Application REGIMEN_OVERLAP is missing from migration 002 core_trace_summary_is_safe. Real registry duplicate-enrollment test with SQL-derived local CHECK simulation rejects the audit summary.
- Production occurrence not verified. Preserve overlap protection and audit; do not swallow failures or invent a different clinical outcome. Evaluate contract compatibility; any required migration needs separate approval and must not be run automatically.

### BUG-07 / P1 — Individually bounded context can exceed database byte cap

- memory.record_context permits six valid Chinese turns which serialize to 22,229 UTF-8 bytes; migration 009 agent_context_bounds allows 20,000. Individual character limits do not enforce the total byte budget.
- Local deterministic reproduction, no live SQL. Assess bounded context construction without altering confirmed patient facts or stored history. No cap relaxation, migration or history cleanup authorized.
- 2026-10-18：UX Polish C 所必需的本地修复使用共享 `contracts/context_bounds.py`，在正常记录与恢复上下文时移除最早的模型窗口片段，预留 16KB UTF-8 总预算。数据库 20KB 约束未放宽，真实保存消息未删除；长中文与隔离 SQL 测试通过。本轮未清洗旧 Session，也未据此标记 BUG-04～09 的其他问题完成。

### BUG-08 / P1 — Read answers omit or mispresent available patient records

- Generic current-list and history renderers return counts/navigation instead of names/date/status; Chinese status rendering omits name and uses inappropriate uncertainty framing. This is distinct from BUG-02's education-specific planner.
- long_term_tools follow-ups show raw UTC (potential different local date); observations silently show two of three existing notes. Synthetic EN/ZH tests demonstrate these gaps; no live provider behavior claimed.
- Rendering must preserve self-report/unknown/estimate boundaries, local dates and explicit result scope. No extra records, fake summaries or persistence changes authorized. Multi-timezone/DST and broad real-model routing still require verification.

### BUG-09 / P1 — General-use questions depend on full product-family matching

- Owner screenshot: Amlodipine choice is recognized but answer provides only non-match/regulatory caveats, not a use. This does not identify the exact runtime provider reason.
- Code evidence: OpenFDAKnowledge.lookup returns missing_form_route_or_release before HTTP when identity metadata is incomplete. matches also requires exact name/ingredient-set, route, form and release; salt equivalence is deliberately not inferred. MedicationUnderstandingService collapses no_reliable_match and unavailable into a single reply and leads general_use with personal-prescriber-reason caveats.
- Existing tests explicitly enforce missing-metadata/no-HTTP and identity mismatch abstention. They verify the current restrictive contract, not that a name-only general-use question is answered usefully.
- Required design: distinguish sourced general ingredient education from verified patient product matching and personal instructions; preserve combination/release/market uncertainty and provenance. Do not simply loosen matches, infer salt equivalence, hardcode drug indications or allow LLM memory to masquerade as a source. Assess additive knowledge match-scope DTO/provider compatibility before implementation; no database migration or patient-record edits should be necessary. No new scope or behavior implemented in this diagnostic round.

### Suggested next scopes (recommendations, not implementation approval)

1. BUG-04: prepare an isolated past-date confirmation safety plan; deterministic reproduction exists, actual model routing remains unverified. Sensitive dose-write boundary, high risk; no backfill authorization implied.
2. BUG-05: date/version-aware read repair; current owned-tool interfaces exist, historical ownership/timezone contract needs review. Medium risk; avoid write-path changes.
3. BUG-06/07: persistence-contract repair review; SQL and application mismatch reproduced locally, production occurrence unknown. Medium risk; assess migration need before implementing. BUG-08 presentation work can follow these correctness gates.

## UX Polish A.1 — local presentation verification (2026-10-17)

- Owner-authorized scope: shared warm-white tokens/container/padding, compact summary buttons, existing report disclosure/readability, selected-plan history progressive display. No Agent, backend API, model, migration, Auth/RLS, dose/inventory or production changes. BUG-01 commit 1ea994b remains intact; BUG-04–09 remain independent unresolved correctness items.
- Existing Today vertical panels, Medicines shortcut/full list, Me three categories and four Records routes were reused. Reports remain deterministic; no new LLM summary or inferred adherence. Existing long forms/export routes remain separate to avoid duplicated state/API.
- History scope was verified against routes/doses.py: selected plan, now minus 7 days through now plus 1 day; UI states this rather than claiming all history. Five fetched entries initially, five more per click, descending timestamp, stable plan-ID query. No new pagination API. Dose/strength distinctions and regimen-version labels preserved.
- Local evidence: 46 focused Vitest tests passed; 8 browser tests passed with synthetic authenticated HTTP, seven requested widths, EN/ZH and 100/150% application fonts, medicine counts 0/1/2/5/10, record counts 0/1/5/20, short/medium/long report export. A genuine Today count-heading overflow at 390px/150%/five medicines was reproduced and corrected without hiding data. Before/after screenshots use identical empty fixtures and 390/1280/1920 viewports.
- Typecheck, ESLint, Vite build and strict new E2E TypeScript checks passed. Existing >500kB bundle warning retained. Browser-native 125/150% zoom controls, physical device keyboards and physical print remain unverified; effective CSS-width reflow and print-disclosure lifecycle were tested. No live/provider tests substituted.
- Source work remains uncommitted. External staging was observed during this task; the assistant did not stage or alter that index. Review final working-tree versus staged versions separately. Detailed local report and screenshots: outputs/UX_POLISH_A1.md. No deferred implementation gate is lifted.

## A.1 Records functional completion — local verification (2026-10-17)

- Owner authorized Records filters/read sorting only. Existing five-at-a-time disclosure was real React behavior, previously tested against synthetic HTTP; the supplied design-board preview was not runtime evidence. This round additionally exercised actual App at `/` against real local FastAPI routes/services with DEMO_ONLY memory persistence and a synthetic token verifier. No production records or credentials.
- Plan ordering: effective_from descending, unknown dates last, stable regimen ID ascending on ties; neither status, version, creation time nor response order determines recency. Medicine and plan use stable IDs. Relative 7/30/90-day controls invoke existing days parameter (backend permits 1–90), with fetch cancellation and expansion reset on scope change. No new API/schema.
- Scheduled history retains due_at ownership; unscheduled/PRN reports use event_time. Future schedule entries are excluded from past history; reported=false stays unrecorded. Times display in patient preference timezone. Existing HTTP assigns event_time from server clock and does not expose created_at in this DTO, so the UI explicitly does not claim actual ingestion time or reconstruct full backfill audit. DB-01/02 and BUG-04–09 remain independently gated/unresolved.
- Local results: 29 frontend tests, 8 actual ASGI route tests, 8 browser tests passed (one real local HTTP journey plus seven existing synthetic HTTP regressions); TS/ESLint/build, new E2E strict TS, Ruff/format and working-tree diff checks passed. Actual journey covers 0/1/5/6/20 past records, current/ended plans, creation/effect-date reversal, local midnight, EN100%/ZH150%, seven widths and real date-query result changes. Initial locale expectation, filter-label CSS specificity and stale test-server/automatic reminder fixture interference were diagnosed and corrected; no assertion skipped or product reminder behavior changed.
- Limits: no production Supabase/browser session verified; no arbitrary date interval or >90-day/all-history claim; no actual ingestion timestamp/backfill write added. Existing active-plan GET can materialize scheduled occurrences, so it was not probed in production. Full local details: outputs/RECORDS_FUNCTIONAL_COMPLETION.md. Changes remain uncommitted; existing index and unrelated A.1/Agent work preserved.


## Records query/grouping correction — local verification (2026-10-18)

- Owner-authorized read-only Records scope adds `/api/me/medication-history/catalogue` and `/api/me/medication-history`; no schema, dose-event write, inventory or confirmation changes. The previous A.1 selected-plan/7-day description remains historical evidence and is superseded for this new Records UI only.
- Registration IDs remain separate even when names match. Product ID and explicit regimen `supersedes_id` are preserved; no inferred name-based version chain or production deduplication. Catalogue sorts effective time descending then stable ID descending. Reviewed source strength is distinct from dose amount.
- Default all medications/all related plans/30 local calendar days; 7/90/custom/all stored history/selected-plan period supported. Two keyset streams merge past stored occurrences by due_at and unscheduled reports by event_time; created_at is disclosed as submission time, not used as occurrence order. Scheduled reports are joined by owned occurrence IDs without a submission-time window. Future doses excluded. Five rows per page, query-bound cursors, snapshot cutoff and stale-response guards.
- Important limitation: this read never materializes missing schedules; all history means all available stored rows, not reconstructed historical doses. Metadata reads fail explicitly beyond 2,000 rows; selected-medication queries with more than 100 plans require a narrower plan. Existing legacy dose-history and Agent tools are unchanged. BUG-05/BUG-08 Agent date/version/rendering issues are NOT declared resolved; this is a separate corrected Records read path.
- Evidence: 60 focused backend tests, 16 component tests, two browser tests passed. One browser test uses actual React App -> real local FastAPI -> DEMO_ONLY memory storage (not mocked business HTTP); provider PostgREST paging/error tests use MockTransport. Seven widths, EN100% and ZH150%, custom local midnight, DST boundary, late report ownership, mixed stream pagination and cross-owner rejection covered.
- NOT VERIFIED: production Supabase PostgREST execution/RLS for the new path and the real screenshot registrations' provenance. No patient data accessed, merged or cleaned; no migration, publication or deployment. Existing owner RLS predicates and JWT-based client are reused. Local implementation/test does not establish hosted availability. Further Agent audit repairs retain their existing approval gates.


### REC-01 / P1 ? Trusted ingredient grouping for Records (2026-10-18)

- Owner requested one top-level ingredient group across strengths and registered medication IDs, without name-based inference. Confirmed blocker: core product schema stores ingredient_names only; source-extraction ingredient RxCUI is not backed by a verified concept/mapping service or persisted authoritative ingredient relationship. Different product IDs cannot by themselves prove a common ingredient set. Evidence and minimum independent proposal: docs/RECORDS_INGREDIENT_GROUPING_PROPOSAL.md.
- Not implemented: ingredient groups and group-wide read aggregation. No schema, production mapping/backfill, patient registration merge or write changes authorized/attempted. Preserve stable medication/product/regimen/event links; unknown identities remain separate. Approval gate: choose verified ingredient namespace/provenance and specifically approve any necessary additive schema/mapping scope; then implement owner-scoped group resolution/read pagination and isolation tests.
- Local safe subset implemented: searchable real-name labels, Unicode/case-insensitive matching, native-select keyboard/mobile support, clear/all options, no patient-visible UUIDs, distinguishable duplicate labels, truthful per-unit strength/per-dose/frequency/effective dates. Short record plan provenance replaces repeated full descriptions. Re-selecting an unchanged filter no longer clears results without refetching (real browser reproduction plus regression test).
- Local tests:61backend,21frontend component,1real browser journey passed; actual App/local FastAPI/DEMO_ONLY memory storage, not production DB. Seven widths EN100%/ZH150%; provider contract mocks remain separate. Typecheck/lint/build/Ruff/worktree diff passed. Production ingredient mapping and hosted/device acceptance NOT VERIFIED. Existing BUG-05/08 and prior approval conditions unchanged.


#### REC-01 owner clarification and follow-up (2026-10-18)

- Owner explicitly requested grouping equal medication display names for Records browsing, with all distinguishing information in plan options. That UI/query requirement is now IMPLEMENTED AND TESTED LOCALLY; it does not require ingredient equivalence. Earlier notes about blocked ingredient mapping retain historical context but no longer block this display-name request. Ingredient-code/schema mapping remains unimplemented and unnecessary for the approved name-filter scope.
- Read-only medication_name resolves all matching owned medication IDs using exact normalized names, never fuzzy aliases/strength stripping. Specific-plan validation and cursor binding preserve scope; records/identities are not merged. Synthetic Amlodipine group returns27recent rows from two registrations and selecting a plan returns only its20rows. Foreign patient/group and mismatched-plan/cursor requests fail.
- Enrollment display refinement: choose days OR last day, calculate inclusive counterpart using calendar arithmetic, keep existing start/end DTO fields and confirmation/write services. Grid sibling margin and time-row alignment corrected; narrow-screen time gets its own full row. Success-only notice auto-fades/removes after4.5s; errors/confirmations do not auto-dismiss. No clinical duration recommendation or inferred course added.
- Evidence:62backend,29frontend component and3browser tests passed (actual React/local FastAPI/DEMO_ONLY storage). Actual local enrollment saved computed start/end through existing review/challenge/activation; same-name group real query, six/seven widths, EN and ZH150%, native search/keyboard, persisted dates and success timeout covered. Existing production/physical-device verification remains NOT RUN; no migration/production changes/index operations/deploy. Existing Agent and ingredient-mapping approval boundaries retained.


### REC-02 / P1 ? Unconfirmed plans entering Records (2026-10-18)

- Confirmed defect: RecordHistoryService previously exposed all owned registrations/regimen states in catalogue and read scope. A reviewed source is not activation. Local fix restricts catalogue and query to active/ended/superseded plans and their registrations, excluding source-only/draft/pending_clarification records even under same-name grouping or direct-ID access. Ended/superseded confirmed history remains queryable. Explicit all-plan scope is bounded to100confirmed plans; wider scope must be narrowed, not silently truncated.
- Real browser exposed two connected pending-flow issues: saved draft was not reflected in App's cached pending list until activation; refreshing a resumed plan snapshot reset its review/confirmation screen. Local enrollment now refreshes pending metadata after draft persistence and avoids reloading an already resumed ID merely because the parent snapshot object changes; pending resume disables review until loaded.
- Local results:66backend tests; actual React/local FastAPI cancellation -> pending list -> resume -> explicit activation -> Records presence journey and existing Records regression passed with independent synthetic owners. Unit regression and frontend checks recorded in status/RECORDS_CONFIRMED_DRAFTS_20261018.md. Production deployment and real patient verification NOT RUN. No original data removed.

### DB-06 / P1 ? Confirmed draft hard deletion

- Owner requests Delete draft + explicit confirmation and real database cleanup. No existing deletion API/repository port; core_guard_regimen/challenge forbid deletes, reviewed source immutability, evidence RESTRICT foreign keys/no ordinary DELETE grants, and audit_events append-only+regimen FK prevent a safe frontend-only implementation. Concrete proposal: docs/DRAFT_DELETION_PROPOSAL.md.
- 2026-10-18 owner authorized local draft deletion and removal of DELETE trigger restrictions. PARTIAL / IMPLEMENTED LOCAL: migration 202610180027 removes DELETE events from five existing guards while preserving insert/update validation, revokes generic DELETE, and provides owner-scoped atomic SQL RPC + retryable private-image cleanup receipts. Typed DELETE API and explicit cancel/confirm UI implemented. No production migration, history rewrite or audit-retention change.
- Local evidence: tests/backend/test_draft_deletion_sql.py (6 real isolated PostgreSQL tests: physical deletion, direct-delete/cross-owner refusal, audit refusal without partial deletion, concurrent retry, storage receipt ownership, confirmed-plan refusal and existing overlap guard); tests/backend/test_draft_deletion.py (4 HTTP/provider/edited-marker tests); frontend/e2e/medication-entry-management.spec.ts (actual App/local API, discard/cancel/delete and loose-pill routing). Browser API uses DEMO_ONLY in-memory persistence; SQL tests independently exercise real PostgreSQL.
- Remaining BLOCKED scope: audit-linked drafts still refuse deletion (audit_events append-only + regimen FK); complete removal requires separately approved audit reference/retention design. Shared sources and confirmed clinical records remain protected. Image cleanup failures return cleanup_pending and durable receipts; retry UI is current-page only, no durable pending-cleanup list yet. Production execution and hosted/device checks NOT RUN.
- Proposed first scope: atomic owner-checked pure-draft-only cleanup with cancel/confirm UI, stale-version/race/retry protection; preserve confirmed clinical/history/shared records. Refuse protected audit/history references unless separately approved retention/reference design exists. Full deletion of audit-linked drafts needs that decision; not implied by a generic cascade.
- Approval gates: local controlled hard-delete implementation/migration and isolated PostgreSQL/RLS tests; production migration and any real patient cleanup remain separate approval. Sensitive scope/high risk. All original approval gates and IDs retained.


## 2026-10-18 Agent Correctness 01 — local implementation, not production closure

Owner explicitly authorized temporal/history/safety local repairs and isolated SQL, not historical backfill or production028. This update supersedes the earlier reconciliation's current-state claims only for the tested behaviors; original findings, IDs and approval gates above remain.

- **BUG-04 — PASS local / production NOT VERIFIED; release safety gate remains.** Past/unsupported calendar claims are blocked before preparing confirmation in both deterministic and model-tool paths. Agent occurrence preparation and execution recheck the patient-local date and actual plan binding; confirmed tool execution also checks the current session. No historical write API or backfill capability added. Current EN/ZH confirmation-only, old occurrence refusal, original audit and existing confirmation/idempotency/isolation tests pass. Until the fix is approved and deployed, a production runtime containing the old path may still propose the wrong date; local success does not resolve that risk.
- **BUG-05 — PASS tested local calendar read contracts / provider and production NOT VERIFIED.** Pure calendar parsing, patient-preference zone, midnight-to-midnight UTC windows (23/25-hour DST), additive status/schedule/history date parameters, effective-interval read service, same-day plan switches and original occurrence/event associations. Historical rule preview is read-only and does not invent occurrence IDs. Late-submitted existing events are joined by patient-owned occurrence ID. Missing effective intervals never select the newest plan by guess. Actual PostgreSQL repository/RLS ended-plan history read also passed. Status reads expose saved occurrences/reports; complete historical schedules are not reconstructed or written. Ambiguous unsupported dates clarify; historical backfill remains unapproved.
- **BUG-06 — PASS isolated PostgreSQL / production Migration BLOCKED awaiting separate approval.** New `202610180028_agent_overlap_audit.sql` adds only the existing closed `REGIMEN_OVERLAP` error value to the redacted-summary function; 1024-byte/key/value checks, overlap guard and RLS stay. Rollback refuses while new overlap audit rows exist. Real registry business refusal → real SQL trace INSERT → owner-only SELECT tested; arbitrary values still fail. Earlier migrations including026 remain unchanged. Do not deploy assuming production028 has run.
- **BUG-07 — already locally repaired by C; additional PASS actual PostgreSQL.** No new memory implementation or cap increase. New tests include Chinese/English/emoji, maximal clarification candidates and summary, complete serialized JSONB budget, deliberate oversized rejection and intact full thread history. C restore/isolation/consent regressions pass. Production rollout and old persisted session shapes remain NOT VERIFIED.
- **BUG-08 — PARTIAL.** EN/ZH four-state named dose answers and follow-up local timestamps repaired. Original audit still FAILS current-list names (2), detailed history answers (2), observations completeness (1); these five remain Correctness02, without skipped/relaxed assertions. Date-only values are not forced into UTC timestamps. Broader provider answers are not verified.
- **BUG-09 — unchanged; Correctness02.** No knowledge-source/indication matching changes or live Gemini calls in this round.

Evidence: `status/AGENT_CORRECTNESS01_20261018.md`, original30 baseline10PASS/20FAIL → final25PASS/5FAIL; targeted regression262PASS (includes37 initial new cases), final expanded temporal tests40PASS; actual SQL30PASS (25 new+5 thread) with final expanded context25PASS. Counts overlap; do not add them as unique coverage. No frontend edits, production SQL, patient history mutation, Git index mutation, commit or deployment.

Next useful authorized-scope proposal: Correctness02 (BUG-08/09), P1/medium clinical-answer risk; read/date contracts and shared30-case baseline are ready, but live Gemini/source evidence and the five remaining patient outcomes are unverified. It needs separate implementation authorization. Separately approve028 production execution and backend rollout only after reviewing this round; readiness is not approval.

### Records page error isolation and current-medicine visibility (2026-10-18)

- User screenshot showed a global “Please review this” popup on Records and an empty medication filter. The implementation confirmed that hidden routed screens can portal retained errors above the active page, and Records coupled medicine visibility to the history catalogue request.
- Local fix: `ErrorNotice` now suppresses its portal when hosted under a hidden page; Assistant also renders retained errors only while active. Records shows currently active medicines from the App's already-loaded patient-medication response independently of history reads, and presents history failures inline with a retry action. No API, query semantics, medication writes, or patient data changed.
- Evidence: frontend unit suite 235 passed; focused local FastAPI history tests 26 passed; browser regression against the real React App with a synthetic 503 history-catalogue response passed. The screenshot's actual request status/body was unavailable, so the underlying history-service failure is not diagnosed; if it persists, history rows remain unavailable while current medicines stay visible. Hosted behavior NOT VERIFIED.
