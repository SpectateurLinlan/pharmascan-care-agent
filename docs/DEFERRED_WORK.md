# MediThread — Deferred Work & Approval Gates

## Interval first-dose collection — owner supplement (2026-10-18)

- **U18 / local scoped PASS:** owner explicitly approved asking for the first-dose time and using a disclosed08:00 default when left blank. This supersedes the earlier approval gate for this local interval-plan repair, not production writes or migration permissions. Evidence and public-contract/deployment notes: `status/INTERVAL_FIRST_DOSE_20261018.md`.
- Manual and source-review forms now collect interval hours and first time; the course start date anchors the first dose. The review and confirmation show default08:00 distinctly. New interval JSON records `interval_anchor.local_date/local_time/time_source`; source evidence stays intact. Application services validate before writes; existing review/B14/ownership/overlap controls remain. Whole-hour intervals1–720 use continuous elapsed-hour expansion across dates and DST, rather than a once-daily08:00 fallback. No migration, backfill, intake/inventory write or existing-plan rewrite.
- Agent uses the existing session service and a typed `prepare_interval_enrollment` model tool: asks before drafting, accepts a time or explicit default choice, asks for a date when missing, expires after10minutes and discards pending collection on topic switch. It does not restore a prior confirmation or activate a regimen. Source-linked reconciliation asks for the corresponding form inputs; it does not approve sources from chat. Live Gemini selection NOT RUN, production NOT VERIFIED.
- An existing interval without a reviewed anchor remains unavailable for automatic Today classification until a new plan is reviewed through the existing version/overlap flow. No automatic08:00 reinterpretation of historical plans. Coordinated backend-first release is required: old strict DTO readers do not understand non-null new anchor/pending metadata. Keep C01 migration028 and other release gates separate.
- Evidence: scoped backend105PASS and final model/photo/new-interval46PASS (overlapping; not summed), thread safety6PASS, isolated PostgreSQL1PASS; frontend focused11PASS plus final4PASS with overlaps; actual-route browser2PASS (EN/default confirmation and ZH150 first-time input). Typecheck/lint/build/Ruff/diff checks pass; real provider and production NOT RUN.

## Records42703 and Today attention — latest local repair (2026-10-18)

- Owner explicitly authorized fixing U16 Records feedback and tidying unreported timed doses. Matrix/report: `status/RECORDS_TODAY_ACCEPTANCE_20261018.md` (RT-01～05). This supersedes the prior “Records unresolved” local implementation status, not its production verification gate.
- **REC-01 / U16: PASS local, production NOT VERIFIED.** Actual SQL reproduced42703 from selecting027-only `patient_edited`; Records now reads available physical columns and normalizes DTOs while preserving newer flags. No027 migration required for this read. Scoped count/paging/owner guards remain. The separate503 envelope is not independently diagnosed as the same fault; failure remains explicit/retryable. Removed rejected current-medicine section/fallback sentence; desktop/mobile/EN/ZH150 actual App checks pass.
- **Today new read projection:** unreported scheduled doses leave attention at the earlier of due+2h, next planned instant or local midnight, moving into a compact “Not recorded” disclosure. This is not an intake fact or late-dose instruction. No Dose Event/occurrence closure/inventory write, no historical reconstruction. Existing reported states are unchanged; active confirmations are not unmounted by refresh. PRN is separate and not a daily missing dose. Authenticated `GET /api/me/today-attention` plus optional `attention_only=true` on the existing due read; default Agent/API behavior retained. Backend must precede frontend; no deploy performed.
- Evidence: relevant backend104PASS + final interval guard1PASS; isolated PostgreSQL1PASS, frontend239PASS + final4 overlapping overview tests (one new), browser3PASS. No C02 full rerun or live production operation. Screenshots/SQL evidence linked in the report; original8 uncommitted C02 paths retained.
- **New concrete schedule limitation / review needed:** `enrollment.py` dose-rule construction uses `local_times or ["08:00"]` even when a stored frequency is interval. No trusted interval anchor is proven by this fallback. This round makes Today return unavailable/review-required for interval/no-anchor data, rather than inventing a scheduled/unrecorded08:00. It does not fix sensitive enrollment/plan writes or assert that production patients have these plans. A separate interval-anchor/source-integrity proposal is required before write-path correction. Keep this one issue rather than renumbering BUG-04～09.

## Agent Correctness02 — local implementation and evidence (2026-10-18)

- Latest scoped update to **BUG-08/BUG-09/AG-03**, superseding older “not implemented” statements for local code only. Original30 baseline25PASS/5FAILED; the five current-list/history/observation omissions are repaired and original30 now pass. Actual replies name products, dates and four patient-report states; rolling health windows no longer inherit calendar-week omissions. Bounds are explicit, not silent truncation. No historical dose writes enabled.
- **BUG-09: PASS scoped local + public source, NOT VERIFIED Gemini/production.** Ingredient education uses exact complete ingredient sets, independent of strict personal-product matching. Cached real source regressions and final two live openFDA requests matched with actual facts/citations. The initial Metformin failure is preserved and led to a USP/label-subject parser fix; no drug-use dictionary or salt equivalence inference. Total public FDA requests7; Gemini0.
- **AG-03: IMPLEMENTED/PASS local.** Owner C02 explicitly approved typed dynamic selection. Shared Today/Workspace buttons and text restore the read intent; current owner, conversation, stable displayed candidates/version and10-minute TTL revalidated. Personal-plan ambiguity keeps exact products; restored old buttons safely expire. No write confirmation or stale tool execution is restored. AG-04 realtime/SSE remains unchanged, not claimed implemented.
- Evidence: `status/AGENT_CORRECTNESS02_20261018.md`, `outputs/AGENT_CORRECTNESS02_ACCEPTANCE_20261018.md`, full actual `AGENT_CORRECTNESS02_CONVERSATIONS_20261018.md` (three20/18/20-turn scenes + nine short scenes,87 turns), separate actual SQL/browser/live-source transcripts. Major regression326PASS, SQL32PASS with final3 overlapping SQL increments, frontend236PASS with focused20 overlapping; browser main path and latest exact-product increment separately PASS. Do not sum overlapping runs. Full real Gemini NOT RUN; no provider success inferred from a configured key/model.
- New read metadata respects16KB UTF-8 budget without deleting durable turns; actual PostgreSQL JSONB/RLS and retained-history tests passed. No new Migration or production operation. Old clients can send text; deploy backend first. Old `extra=forbid` backend readers cannot read new context fields: coordinate replacement/compatibility rollback, not patient-history cleanup. C01 production028 and unsafe-old-runtime release gates remain independently blocked pending owner authorization.

### Latest Records runtime feedback — separate, unresolved

- Owner supplied actual envelopes `INVALID_INPUT` / Supabase HTTP400 code42703 and `PROVIDER_UNAVAILABLE`, plus a screenshot contradicting a functioning catalogue/history path. This is **EVIDENCE CONFLICT** with any broad completion claim, not proof that a mock fallback repaired live queries. Exact rejected column/request/version remains unverified; do not guess a migration or broaden schema permissions.
- Owner rejects the added “current medicines” subsection and “above still shows current medicines” fallback explanation, and reports overlapping layout. Link register U16 / MT-REC-01/04/08. These changes are not performed as a side effect of C02; owner most recently requested continuing C02 without rerunning solved work. The prior local235/mock503 browser evidence remains historical only, not a PASS for this new feedback.
- Next useful scopes (not automatic implementation approval): (1) bounded real Gemini synthetic acceptance after quota/cost/environment are confirmed, read-only medium-risk; (2) Records request/schema diagnosis and removal of rejected UI, preserve read-only/patient scope, no production migration without approval; (3) separately review/authorize C01 production028 and coordinated backend/frontend rollout. No automatic deploy or production patient edits.

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


### 2026-10-18 Final Integration — current evidence supersedes earlier local-only gaps

- **DB-06 / MT-ENR-11**: pure-draft real PostgreSQL RPC deletion plus actual FastAPI/application-to-RPC/refetch404 and retry now verified. Cross-owner/direct delete/protected audit or confirmed history remain atomically refused. The current owner explicitly accepts protected-history refusal; this is not permission to delete audit history. Production metadata READ ONLY found001–026 hashes matching,027/028 PENDING; deletion RPC and patient_edited absent. This is a production release blocker, not patient INVALID_INPUT. No production mutation.
- **BUG-06 / MT-AGENT-07**:028 remains pending production approval; isolated full-chain and026→027→028 upgrade verified, current SQL guard/audit/RLS preserved. No new migration added in final integration. Migration inspection helper no longer performs implicit ledger DDL; actual READ ONLY PostgreSQL test passes with/without ledger.
- **REC-01/REC-02**: pre027 actual physical projection reproduces42703; approved adapter fix avoids DTO-derived nonexistent columns. Actual browser Records/Today queries passed; redundant Current medicines fallback and its explanatory message have been removed per later owner feedback. Earlier fallback-visibility acceptance is SUPERSEDED, not the desired final UI. No occurrence fabrication or automatic not-taken writes.
- **BUG-08/09 / MT-AGENT-03/05/06/08/09/10**: original30 patient semantics PASS locally;45 actual Gemini wire requests, two continuous12-turn runs and targeted followups captured in outputs/REAL_GEMINI_RELEASE_QA.md. Initial plural-name, source-followup, weekly-history and provider failures retained; necessary routing/renderer fixes and source-entity state added. Historical self-report explicitly refused before model with no proposal/write. Some paths intentionally records_only, not Gemini tool-selection evidence. No95%/clinical/production claim; identical grounded explanation/source duplication now fixed without merging identities; broader naturalness/hosted verification remains limited.
- **MT-VOICE**: abort/navigation/timeout state recovery and6s notice expiry implemented; simulated browser + actual UI verifies cancelled speech preserves draft/no auto-send. Real Android recognition remains NOT VERIFIED.
- **Multimodal**: real Stage2 v0.10.0 through actual FastAPI preview for package/pharmacy-label/prescription; actual routing and unknown-pill refusal. Initial check-input503 was test composition missing routing injection, corrected and preserved as initial evidence. ER release/duration/clock structured extraction remains incomplete; mandatory review retained, explicit printed HH:MM conflicting review now rejected. No Stage2 model changes or confirmed identity from similarity. Actual personal embedding/match with local private Storage now verified: self-comparison match, foreign404, retire then missing_reference; no ingestion/clinical identity claim. Patient-calendar hardcode and unvalidated count-reliable claim corrected with37 focused tests. Real hosted Storage/Auth remains NOT RUN.
- **Summary**: existing deterministic counts retained; overview/highlights/questions/detail hierarchy and full numeric observation values now rendered and exported. Actual browser128/82 and3notes verified; no inferred adherence percentage/diagnosis.
- **Repository**: hash-backed duplicates removed; status/outputs operators classified under private internal/operations;8 superseded code rewrite helpers deleted only after verifying retained targets; unique history/Tencent evidence preserved. File Catalog generator separates manual metadata; no Git index mutation.
- Unified current gates/approval: status/RELEASE_READINESS_20261018.md. No Commit/Push/Deploy/new production SQL/Secrets/Cron, no production synthetic patient writes.

- Final continuation: EN/ZH10-turn sequences added; records for this week incorrectly became a medication filter, fixed by separating calendar words from entity input. Actual repaired reads and47focused regressions pass; original failed turn retained. Total45Gemini requests, no production writes.


### DB-07 / P0 — hosted default ACL reconciliation (2026-10-18)

- Evidence: actual production metadata READ ONLY matches026 business objects, but ACL expansion has250extra entries including non-patient service-role administration and unnecessary anon/authenticated rights. Information-schema grants omit PG17+MAINTAIN, so canonical inventory now uses aclexplode; column/default ACLs are captured separately. No production exploitation finding is inferred.
- IMPLEMENTED LOCAL: new029 revokes anonymous patient-table access and unnecessary table/DDL/direct-write rights, restores intended guarded UPDATE(data) for reference retirement, restricts future tables for migration-owner defaults. No clinical row changes, new trigger or widened service privilege. Platform-owned supabase_admin defaults remain a separate owner boundary; future DDL must revoke inherited broad grants explicitly.
- VERIFIED: real captured-grant replay026→027→028→029; business objects unchanged except intended new objects,101grants narrowed.45related actual SQL cases passed across16upgrade/delete/thread and29temporal/Agent/Records cases; counts overlap earlier runs. Real Gemini→new029PostgreSQL/RLS verified with cached public label fixture; cumulative45wire requests, all failures retained.
- BLOCKED PRODUCTION:027/028/029require one owner-approved release operation; no production writes, Git commit or deploy. Source/hash/scope and recovery are in status/RELEASE_READINESS_20261018.md.


### MED-UX-01 / P1 — Ongoing medication identity editing (2026-10-18)

- The medication-detail refactor requested an `Edit Medication Information` action for an already active or historical medication, separate from initial enrolment. Repository inspection found no patient-scoped identity-only edit API or application workflow. `EnrollScreen` edits regimen instructions as a new regimen version; `EvidenceEnrollmentScreen` can review a saved source and prepare activation. Reusing either as product editing would conflate identity correction with regimen creation or activation.
- This UI refactor therefore keeps source evidence and medication gallery access, but does not add a misleading identity-edit button or restart enrolment. User impact: a patient cannot correct or supplement canonical product identity fields from Medication Detail.
- Proposed prerequisite: an independently reviewed public API/application contract for identity-only edits that preserves medication IDs, source links, provenance and audit history, checks same-name/product conflicts, and cannot change active regimen instructions. Add owner-scoped negative and version/history tests before exposing the UI action.

### MED-GALLERY-01 / P1 — Scalable reference-photo lifecycle and structured provenance (2026-10-19)

- The gallery UI now searches the fields present in the current patient gallery response, filters/sorts and incrementally renders 12 records at a time, scopes product/photo views by medication ID, and supports a private-photo detail view. Add-photo is available above the grid; capture is user initiated, device file choice is separate, content and provenance are separate controls, and comparison defaults off.
- Existing enforcement found in code: evidence upload accepts PNG/JPEG with signature validation and an 8,000,000-byte request limit; the shared image normalizer caps decoded images at 16,000,000 pixels; private Supabase buckets use a 10 MiB object cap and owner policies; visual comparison considers at most 50 compatible embedded references in one run. No separate per-product reference count or total patient-storage quota was found. The UI does not invent a count limit; it mirrors the 8 MB application upload limit.
- The persistent gallery endpoint still returns all metadata in one response, with no server pagination. Product identity is represented by owned medication IDs and the latest enrollment product summary; there is no generic ingredient grouping contract. Source provenance is persisted through the existing free-text `source_description`, not a structured provenance field. The photo API supports retirement from visual comparison but has no metadata-correction or ordinary-photo deletion contract; this UI does not offer those operations.
- Local evidence for this supplement: `frontend/src/components/MedicationEvidence.test.tsx` 19 passed; `tests/backend/test_medication_evidence.py` 26 passed; synthetic authenticated Playwright gallery journeys 2 passed; typecheck, ESLint, build and scoped Ruff checks passed. Private Storage, authenticated hosted routes, desktop/mobile physical camera permissions and real-device rendering were not exercised. The mock browser test does not prove hosted access control or persistence.
- Next approval boundary: design and review an owner-scoped API/application contract for structured provenance, server-side paging/thumbnail batching, quota reporting and supported metadata/deletion lifecycle operations before implementing persistence changes. No migration or production storage action is included in this UI work.

### Medication management acceptance resume — 2026-10-19

- The active-plan dead end now enters the existing reviewed draft/B14 flow with an explicit `supersedes_regimen_id`. In-memory tests verify no-stop activation, predecessor history and version 2. Migration `202610190030_regimen_successor_activation.sql` atomically retires the predecessor, reconciles open future occurrences without deleting dose events, replaces rules, and appends redacted activation audit rows. The overlap guard exception is limited to the named same-medication predecessor. Migration and rollback files are local only; no production migration was run.
- Local evidence (final focused rerun): enrollment/Supabase adapter/long-term-care 79 passed; frontend focused 46 passed; Chrome synthetic medication-detail flow 1 passed; typecheck, lint, build, Ruff/format and Impeccable detector passed. The successor test also checks disabled old rules, closed unreported future occurrences and new schedule rules. Actual PostgreSQL migration/trigger/RLS/schedule behavior remains **NOT VERIFIED** because the isolated PostgreSQL DSN is unavailable (six SQL tests skipped); do not claim the database workflow complete until isolated SQL acceptance passes.
- Knowledge, inventory, history, photo-preview and the two direct medication-entry actions have synthetic browser/component evidence. Live provider, real patient storage, persistent stock writes, authenticated hosted UI and device behavior remain separately unverified.
- `MED-UX-01` remains OPEN. This medication-detail work did not add identity-only editing or conflate it with regimen version creation.
- Detailed behavior matrix and commands: `status/MEDICATION_MANAGEMENT_20261019.md`.
- Approval gates: separate owner approval for that contract and implementation. No schema, API, identity write or production change is authorized by this deferred entry.


### 2026-10-19 — production 027–029 and release answer verification

- DB-06 / BUG-06 / DB-07: owner-authorized027,028,029 applied in production in that order; ledger hashes and actual RPC/RLS/audit/ACL checks PASS. No production patient inserts, success-delete tests, backfill, Secrets, Cron, Push or deployment. The old backend's guarded conversation and image-retirement RPCs, owned medication reads and Push PATCH grants remain. Hosted authenticated UI/Storage/device acceptance is still separate.
- A full private custom archive plus password-free role definitions was created outside Git under owner/SYSTEM-only ACLs. Restored public/auth/storage69tables with identical snapshot row counts and digests. Storage object bytes, platform settings/secrets and PITR are not covered by this database validation. Exact private location and proof are in the local execution record, not in Git.
- MT-AGENT-12: SDK-owned single bounded retry, 12s per attempt, bounded backoff; no outer Agent/Tool retry. Actual SDK transport503→200 and exhaustion tests PASS. New real run had16requests, all200; older5real503 preserved. No claim that temporary provider outages are eliminated.
- BUG-08/BUG-09/AG-03: first after-fix EN16/ZH8 had an EN historical-status routing failure; retained. Repaired the named status query precedence and language-independent choice versioning. Complete final EN16/ZH8 fact/tool checks pass, with real Provider and deterministic routes explicitly separated; source brevity/naturalness remains PARTIAL. Full replies appended to existing local REAL_GEMINI_RELEASE_QA.md, not replaced by a rewritten ideal transcript.
- OCR client now quotes explicit ER/release, clock and duration words as unconfirmed review hints; it does not populate or approve a regimen. Actual390/1280App captures and browser interaction PASS with explicitly synthetic HTTP/OCR fixtures. External Stage2 structured field completeness remains independent.


### AG-03 / AG-04 / Correctness 02 — Patient experience supplement (2026-10-19)

- Current owner-approved refinement: concise EN/ZH patient answers, relevant ingredient/strength choices, trusted comparative selection, automatic read-intent continuation and original-source access. Local implementation is complete for the twelve scoped behaviors; actual before/after replies and acceptance matrix are appended under `Patient Experience Refinement` in `outputs/REAL_GEMINI_RELEASE_QA.md`.
- Direct evidence: 227 focused backend tests (including 26 new cases), two source-component tests and four actual React→FastAPI synthetic browser journeys at390/1280px EN/ZH. Source URLs, original label excerpts and reviewed raw instructions remain available; source brands do not identify patient products. No production write, migration, new Gemini request or device acceptance is implied.
- Boundaries: unknown Chinese translations remain clearly identified English excerpts; conservative strength comparison abstains across unknown/different product families, forms, release types, routes, brands or units. No personal diagnosis/dose inference or historical backfill was added. Prior hosted/device/provider-availability gates remain independent.


### BUG-08 / AG-03 — final real-provider multi-result coverage (2026-10-19)

- Live Gemini smoke after e1adab7 exposed a distinct gap: multiple successful knowledge tools were reduced to the last `patient_safe_summary`, silently omitting earlier medicines. Initial11turn evidence retains two FAILED final replies. Local fix aggregates every executed general-use result, shares evidence only across trusted compatible ingredient/product scope, discloses uncovered entries and preserves structured answered IDs for source follow-ups. No new medical facts or writes.
- Direct verification:15new actual Gemini requests, all200 (76cumulative);5targeted after-fix turns PASS with real Gemini/openFDA and synthetic memory services. The other successful targeted scenarios used deterministic routing and are explicitly not counted as Gemini tool selection. Source UI remains unchanged; prior browser evidence reused. Full actual questions/calls/facts/replies are appended under `Final Provider Integration` in outputs/REAL_GEMINI_RELEASE_QA.md.
- Release boundary: submitted Agent RC needs no030. Uncommitted successor activation calls the030RPC and remains excluded; full workspace release is NOT READY until that independent SQL/RLS acceptance and remaining feature publication are reconciled. No027–029replay, Push, Merge, Deploy or production writes.


### MED-GALLERY-01 — real-user QA follow-up (2026-10-19)

- The earlier attachment supplement is retained as historical evidence. Follow-up source audit found that the personal-gallery upload trusted `image_kind` before calling the embedding service; the existing Stage2 input router was separate. A comparison-requested loose-pill upload now calls that existing router server-side and requires a checked, non-abstained `loose_pills` result before embedding. Mismatch, abstention, classifier/provider unavailability, and ineligible embedding metadata stay associated evidence only. Matching queries accept only the new classifier-backed eligibility reason. Legacy eligible records without that proof are hidden from active comparison by a read projection; the source photo, embedding, provenance and audit rows are not deleted or rewritten.
- Duplicate IDs are based on deterministic SHA-256 normalized image content within the medication identity. Existing rows are reused across repeated submissions and category relabels. Concurrent synthetic submission tests produce one image/embedding per patient-medication identity; identical bytes across patients or distinct same-name medication IDs remain separately scoped. Unsupported image MIME/signature requests are rejected by the existing transport guard.
- Navigation follow-up: route state is now actual browser history state; gallery search/filter/sort use replace semantics, product/all/photo transitions use push semantics, and direct photo gallery URLs preserve all query fields during app initialization. Add-photo is a focused six-step dialog with dirty-state confirmation, bounded desktop scrolling/full-screen mobile presentation, and retained values. Dose verification reuses acquisition UI only; it remains separate from gallery storage.
- Local evidence at follow-up: 35 focused synthetic backend tests; 268 frontend component tests across 51 files before the final route/dirty-handler edits, with 16 affected navigation tests and 24 focused upload/camera tests after the route fix; typecheck, ESLint, Vite build and scoped Ruff/format/diff checks. Targeted Playwright journeys and their scope are reported in the accompanying `REQUIREMENTS.md` supplement. No Stage2 provider call, isolated persistent database/storage run, production write, RLS/Storage change, or physical-device camera test was performed.
- Still deferred: (1) authenticated isolated Storage/RLS verification against synthetic owners, requiring available isolated infrastructure; (2) a structured owner-scoped classifier assessment/version, selected-vs-suggested category and correction/audit contract, requiring an API/schema/RLS proposal and explicit owner approval before implementation; (3) any photo metadata-correction or ordinary evidence-deletion API, structured provenance, per-patient/per-product quota, or server-pagination work. No production migration or historical image mutation is authorized by this supplement.
- Bounded proposal for the second deferred item: after owner approval, extend the existing gallery upload DTO/application contract with a server-owned assessment object (`classifier_source`, model/version, suggested content type, checked/abstained state) while storing the patient-selected type and correction separately. Make comparison eligibility a server-derived result only. Add one reversible migration and patient-owned RLS policy for persisted provenance if existing columns cannot carry it; add synthetic SQL/RLS owner-isolation and correction/audit tests. No client-supplied eligibility flag, automatic historical recategorization, image deletion, or activation of old rows is part of the proposal.
- Final rerun after all local edits: 40/40 affected Vitest cases, 5/5 targeted Chromium Playwright journeys, 35/35 backend image-evidence tests, TypeScript/ESLint/Vite build, scoped Ruff/format and diff checks passed. A previous Playwright run exposed stale dirty-state handling and an outdated step-driven test; both were corrected before the passing rerun. The tests use synthetic authenticated HTTP and DEMO_ONLY bytes, not live patient/provider/Storage data.

### MED-GALLERY-01 — route restoration correction (2026-10-19)

- Scope: local `PersonalGalleryScreen` route hydration and regression coverage only. When the gallery URL contains `medication_id`, that route identity now takes precedence over stale parent component state; `initialMedicationId` remains the hand-off for Medication Detail → `#gallery` before the URL query is initialized. The pending-data state remains explicit rather than presenting an empty gallery.
- Evidence: targeted component/navigation tests 36/36 and gallery/detail Chromium journeys 5/5 passed, including global/product Back and Forward, product gallery → Medication Detail → browser Back, application Back, All Galleries, direct URL and refresh. TypeScript, ESLint and Vite build passed. The owner-reported blank body did not reproduce in the current synthetic environment; hosted authenticated routes and persisted records remain NOT VERIFIED.
- No API/DTO/schema, RLS/Storage permission, production migration, or image lifecycle change. This correction does not implement the deferred MED-GALLERY-01 server paging, structured provenance, metadata editing/deletion, quota, or storage acceptance work.

### MED-GALLERY-01 — classifier and image-retention safety correction (2026-10-19)

- This dated supplement corrects the prior follow-up's unsupported statement that Stage2 `/v1/check-input` classifies image content for gallery eligibility. Contract inspection shows workflow routing, pill detection/embedding, OCR, and candidate matching are separate capabilities; no validated general packaging/label classifier was identified.
- Local application behavior now stores all newly uploaded gallery images as associated evidence, does not create embeddings, disables gallery classification suggestions, and filters historical comparison eligibility unless backed by a currently supported server provenance reason. Historical evidence is not modified. Whether production records contain incorrectly active references was not inspected and remains **NOT VERIFIED**.
- Exact duplicate insertion returns a duplicate status from the existing endpoint using deterministic patient/medication scoped IDs and the existing unique owner key. The frontend preserves upload state and links to the stored photo when present. Memory concurrency is tested; PostgREST conflict behavior is covered at the adapter boundary, while concurrent real Storage object behavior remains unverified.
- No delete button or deletion API was added. The current `retire_personal_reference` operation stops comparison and preserves the stored image; it is distinct from removing the medication association or deleting evidence. Minimum future proposal: owner-scoped application/API delete request with explicit confirmation; transactionally retire/detach references and record an audit event; define retention treatment for embeddings and source provenance; perform retry-safe private Storage cleanup with reconciliation for partial failures; add RLS, cross-owner, duplicate/retry, audit-retention and isolated Storage tests. Review the API/database/Storage contract and obtain explicit owner approval before implementation or any migration/permission change.
- The existing authenticated `store_personal_reference` RPC can independently accept an eligibility-shaped write, because its DB checks do not validate image content. The current app upload no longer invokes it and the matching service excludes every legacy reason. Revoking or hardening this RPC and reviewing authenticated grants requires a separate SQL/RLS proposal and explicit owner approval. No migration or production data access was performed for this correction.

- Correction verification: `38` focused backend tests, `31` targeted Vitest tests and `5` synthetic Chromium journeys pass; typecheck, lint, build, Ruff and format checks pass. Actual isolated Supabase/PostgREST/Storage race behavior and physical camera behavior remain **NOT VERIFIED**. No production migration, database/RLS/Storage mutation, deployment, or patient-data read/write was performed.
- The earlier bounded proposal to persist a Stage2 `/v1/check-input` classifier assessment is **SUPERSEDED**: that endpoint is workflow routing, not a validated general image classifier. Any future classifier proposal must first identify an actually supported general content model and its documented output/limits; it must then define uncertainty, source/version provenance, patient correction and audit rules, and comparison gating. Do not retrofit workflow-routing output into a classification claim.

### 2026-10-19 — Migration 030 production release update

- The earlier release-boundary note above is preserved as historical state. After its isolated PostgreSQL acceptance completed, the owner authorized a fresh protected backup and separately approved migration 030 in the same workflow. The scoped runner applied only `202610190030_regimen_successor_activation`; post-apply read-only verification confirmed the ledger hash, SECURITY DEFINER RPC/fixed search_path, actual function ACL, overlap trigger and public schema/RLS metadata. Local PostgreSQL acceptance passed 12/12. See `docs/REQUIREMENTS.md` and `status/MEDICATION_MANAGEMENT_20261019.md` for exact evidence.
- This closes the database-migration prerequisite for successor activation, but does not close unrelated `MED-GALLERY-01` work or authorize/deploy application code. Hosted backend runtime SHA, authenticated hosted successor activation, and post-release browser/device acceptance remain NOT VERIFIED. Application release needs separate owner approval; database migration did not change RLS/Storage policies or patient rows.
- Production ACL evidence shows EXECUTE for `authenticated`, `service_role`, and owner `postgres`; `anon` and `PUBLIC` are denied. Supabase's default function ACL leaves `service_role` with EXECUTE, so its credential remains server-only. No production audit transition, patient data write, rollback or application deployment was exercised.


### MED-LIBRARY-01: Medication-centred source files (2026-10-19)

- Local implementation: added a patient-authorised, read-only per-medication file aggregation over the existing medication, regimen, source-link, source-document, source-field, evidence-image, and private-image contracts. The global card exposes real source counts and actual available update timestamps. Product Files unifies existing image records, exact-storage-path groups duplicate rows, preserves separate regimen/product medication IDs, supports purpose/content/format filters and reuses private image previews. Source detail is URL/history-addressable and presents extraction suggestions separately from reviewed fields. No schema, write API, permission/RLS, or Storage policy change was made.
- Evidence: backend synthetic service tests cover explicit source IDs, owner rejection, exact-path grouping without name-based merge, and a source record linked to a regimen. Frontend component and synthetic Chromium coverage verify source detail, private-image route use, Browser Back/Forward/direct refresh and EN/ZH labels. PostgreSQL extraction JSON mapping is implemented against the existing immutable column but no isolated PostgreSQL source-document round-trip was available in this run. Actual authenticated Storage/RLS scope remains NOT VERIFIED.
- Supported files: normalized private PNG image rows from gallery evidence and medication enrollment. The product file display derives purpose from actual source_id/record relationships; selected photo category remains descriptive metadata and comparison eligibility remains the existing server-projected value. Exact shared-object grouping is only by identical storage_path inside the selected medication; it does not compare names, checksums, or pixels.
- Deferred boundary: source_documents has no original binary/storage locator in the exposed DTO, the source upload/preview transport currently accepts image content, and private preview only serves PNG. No PDF document bytes or generic document bucket listing were found. Do not show inferred PDFs. A future PDF capability needs an owner-scoped source-file reference, permitted MIME/size/signature rules, private Storage preview/download contract, provenance/retention behavior, and isolated RLS/Storage tests; prepare a separate API/schema/Storage proposal and receive owner approval before implementation. No migration is currently proposed for this task.
- Product IDs: current gallery cards remain keyed to patient-medication IDs, with all regimens nested. Distinct medication records stay separate even when display names match. Do not merge records by generic name; any future cross-record grouping needs confirmed product identity semantics and must retain medication/source/regimen scopes.
- No production data, private Storage, API write, migration, deployment, or patient record was accessed or changed. Preserve this ID and approval gate until real owner-scoped persistence and any approved document-binary contract are verified.


### MED-LIBRARY-01: final purpose-label and regression verification (2026-10-19)

- Corrected file-purpose semantics: every linked image is labelled as stored evidence; enrollment source is added only when a source-document relationship exists; appearance reference is shown only when the backend reports current comparison eligibility. The files read model applies the same fail-closed legacy-eligibility projection as the gallery summary. This is a read projection only; stored evidence, image metadata, embeddings, and audit rows are not changed.
- Final relevant verification: `tests/backend/test_medication_evidence.py` + `test_supabase_data.py`: 61 passed; affected Vitest files: 32 passed; targeted Chromium gallery journeys: 6 passed; full Vitest suite after the final purpose-label refinement: 278 passed across 51 files. TypeScript typecheck, ESLint, and Vite production build passed after the UI refinement; scoped Ruff check/format passed. Existing warnings: pytest cache permission warning and Vite bundle-size advisory. A Ruff format check initially requested one formatting-only adjustment; it was applied and rechecked.
- Environment boundary: all browser and backend tests use synthetic fixtures/mocked authenticated API behavior. No isolated PostgreSQL document round trip, real patient DB/storage access, or authenticated private Storage preview test ran. PDF bytes remain unsupported and are not represented as file cards. New functionality adds a read-only authenticated `GET /api/evidence/gallery/{medication_id}/files` endpoint over existing contracts; it adds no write contract, schema, RLS, permission, or migration change. Backend/frontend release coordination is required before use outside this local worktree.
### MED-LIBRARY-01 supplement - source-file/PDF retrieval gap (2026-10-19)

- Confirmed contract gap: source document DTO/API contains source kind, review state, extraction evidence, fields, regimen links and explicit medication-image IDs. It contains no original-file locator, filename, media type, or PDF preview reference. `MedicationImage.storage_path` is a private PNG image reference; the existing authenticated image route is not a source-document file API.
- Product-library UI now reports source rows from explicit medication/source relationships. `user_manual` is presented as manually entered only when that exact source kind is present. Other rows distinguish recorded extraction/field metadata from a missing image association. Absence of an image link does not establish that the original file was never uploaded, deleted, inaccessible or a PDF.
- Deferred minimum proposal: add an owner-scoped source-file association and a patient-authorized read-only application endpoint that validates source/medication ownership and streams the referenced private object or issues a short-lived signed URL. Never enumerate a private bucket from the frontend. If an original upload is not already stored, separately approve an upload/write contract including consent, signature/MIME/size validation, checksum, retention and audit behavior.
- Approval gates: review public DTO/API and schema/RLS implications; review private Storage access and signed URL lifetime; approve any migration and deployment separately. No migration, RLS/Storage policy change, production data inspection or PDF placeholder was made in this supplement.
- Verification state: frontend component and synthetic browser tests are local only. Authenticated PostgreSQL/Storage scoping, real source-file existence and PDF preview remain NOT VERIFIED until isolated infrastructure and authorized records are available.

### MED-LIBRARY-01 / MED-GALLERY-01: local file lifecycle implementation supplement (2026-10-19)

- Local implementation now adds medication-scoped original PDF files in the existing private `medication-sources` bucket, owner-authenticated content routes, a patient-file metadata/audit table, metadata edits, retryable tombstones, and versioned photo edit/remove/delete RPCs. Migration `202610190031_medication_library_file_lifecycle.sql` and a rollback that refuses to drop any non-empty file/audit tables are local and unapplied. No production schema, RLS or Storage policy was changed.
- Photo management keeps three operations distinct: stop comparison retains the evidence and removes the embedding; remove from gallery retains the private image and prevents comparison; delete requires confirmation, owner scope, no source link/shared path, a tombstone and retryable Storage cleanup. Metadata changes cannot grant comparison eligibility. PDF is never eligible for visual comparison.
- PDF is associated only to the explicitly selected patient-medication ID. The new file entity does not fabricate a `source_documents` or regimen-version relationship. PDF OCR, extraction and enrollment remain future work.
- Synthetic verification: focused backend evidence/PDF lifecycle tests passed 45; full frontend Vitest passed 289 across 53 files; targeted Chromium gallery flow passed 6/6. These use memory repositories, mocked API behavior and synthetic browser journeys only; they do not prove authenticated Storage or PostgreSQL behavior.
- Production/readiness status: **NO-GO / NOT VERIFIED**. No PostgreSQL parser/runtime, isolated PostgreSQL, authenticated Supabase Storage, or browser PDF-viewer integration was available. `psql`, `pg_ctl`, Docker, `pglast` and `sqlglot` were absent. Migration 031 needs independent SQL/RLS/RPC review, isolated migration + concurrency + owner-isolation tests, and separate owner approval before production execution. Coordinate a reviewed backend release only after the migration is approved and applied; no application deploy occurred.
- Known release risks: PDF validation checks MIME/extension/size/header/EOF, not complete parser validity or malware scanning. Storage upload occurs before DB registration; a timeout after object creation may leave an orphan. Do not automatically delete historical evidence or reconcile ambiguous objects without a race-safe, audited policy. The rollback intentionally refuses when file or lifecycle audit rows exist; preserve those records and prepare a reviewed recovery instead of dropping tables.
- OCR/structured PDF understanding was added to the actual About page only as future roadmap copy. No external AI/OCR calls or medication-plan writes were introduced.


### MT-CARE-03 / Today follow-up supplement — 2026-10-19

- Owner explicitly authorized local implementation of controlled late reporting and care-task UX. Historical Agent backfill restrictions remain in force; no production data/Schema operation is approved by this supplement.
- IMPLEMENTED LOCAL: verified min(two hours, next dose, local midnight) attention boundary; default-visible recent unreported occurrences, mandatory patient choice and reason, optional actual time, full-payload confirmation, append-only correction ledger and effective read projection. Read-only ineligible rows remain visible. Original event/plan history and optimistic/idempotent safety remain intact; no inferred missed doses or ingestion proof.
- IMPLEMENTED LOCAL: task modal/field focus/local-zone validation; explicit historical entry without past reminders; advance/no/custom reminders through existing notification queue; legacy version-slot reuse with retry budgets preserved; compact lifecycle views/details/edit/reschedule/reopen and readable history; bounded pending-first Today links.
- Evidence: synthetic HTTP/application and component tests, actual isolated PostgreSQL migrations/RPC/RLS/audit/concurrent writes/queue/guarded rollback, and 3 real Chrome/local-FastAPI journeys (EN/ZH and 390/1280). Exact commands/counts and shared-file boundaries: status/TODAY_CARE_TASKS_20261019.md. Browser Auth is simulated and SQL is verified separately; no hosted or actual Push-delivery claim.
- Release gate: new local032/033 require independent production approval and coordinated backend/worker/frontend release. Old backend strict DTOs and raw-event readers are not a supported rollback after new data exists; use a maintenance window or a separately verified compatibility patch, then forward repair. Empty-only rollback scripts refuse to destroy new statements or task history. Do not automatically include unrelated031.
- NOT VERIFIED: hosted Supabase PostgREST/worker/device delivery and native device picker/accessibility. No external Gemini/notification request, stage, commit, push, deploy or production migration. No031 functional acceptance is inferred from isolated migration-chain parsing.
- Future calendar: only the source-preserving read-only DTO and bounded month-aggregation/deep-link plan were delivered; docs/CARE_CALENDAR_INTEGRATION.md. A separate approved task may implement that bounded read-only scope; no second calendar or reminder source of truth.

### 2026-10-20 Today and Care Task calendar UI supplement

- IMPLEMENTED LOCAL: Today late-report cards now filter unresolved, eligible occurrences by the patient timezone and the server-provided `as_of`; the existing Records route hosts the recent report/correction workflow. No backend eligibility or write rules changed.
- IMPLEMENTED LOCAL: Care Task Calendar/List views share `GET /api/me/care-tasks` data and one status derivation, with independent status filtering, patient-zone date grouping, existing task details/form workflows, and a direct Today creation action. No calendar storage, API, lifecycle state, or schedule changes.
- Evidence: focused Vitest 21/21, synthetic Playwright EN/ZH at 390/1280 widths 2/2, TypeScript, affected ESLint, `git diff --check`, and Impeccable detector passed. Browser API/Auth were mocked; no patient records or backend services were written.
- Hosted deployment and real-user/browser timezone behavior remain NOT VERIFIED. This supplement completes only the local frontend calendar/UI scope; prior 032/033 release gates and Push/device gates remain unchanged.


### 2026-10-19 ? MED-LIBRARY-01 / MED-GALLERY-01 incident and031 readiness update

- Owner corrected the evidence scope: failures originated at localhost5173, not deployed Vercel. Local8001's new code targets an actual Supabase schema whose matching custom ledger stops at030. Read-only catalog evidence confirms absent031 file tables and033 event/report objects; no cache reload can create them. Gallery depends on031; Alerts/history additionally depended on033. The source/real-catalog diagnosis supersedes the earlier speculation that all failures were hosted or due only to031.
- Safely implemented locally: explicit pending-feature switches (default off), schema030 event/history compatibility,503 infrastructure error mapping with scrubbed logging, failed-read versus empty-gallery distinction, capability-gated031 controls, bounded Alerts failure backoff, and additive effective feature readout in `/api/health`. Owner-authorized API-only reload was observed, with both flags false and the existing5173 frontend retained. No patient-bearing authenticated production request was made.
- Actual patient list/history counts remain **BLOCKED/NOT VERIFIED**: no existing JWT context was accessible to automation; both unauthenticated local list requests correctly returned401. A local-only counts script reads the existing browser SDK session without printing token/record contents. History remains terminal chain tips only. A past planned end date can exclude an active row from Current while History excludes non-terminal states; this is a code-level presentation risk, not proof of this patient's missing records. Do not mutate lifecycle data or silently reclassify active regimens.
-031 verification progressed to **26 PASS on real isolated PostgreSQL17.11**. Corrected local unpublished SQL: JSON storage/checksum references, null-version/action guards, stopped-comparison audit action, atomic embedding retirement, and serializing new image associations with tombstoning. Empty rollback/reapply, nonempty refusal, RLS/ACL/owner checks, duplicate/concurrent writes, protected sources, audits and race tests pass. This supersedes the earlier tool-unavailable statement for local SQL only; no production031 application occurred.
- File upload recovery is still **PARTIAL**: deterministic-key retries converge after ambiguous registration; preflight avoids active duplicates/known tombstone recreation; no blind Storage compensation. Abandoned uploads can leave private orphans and cross-service PDF upload/delete races need durable reservation/reconciliation design. Do not sweep private buckets or delete historical evidence.
- **Release gate remains NO-GO**: no isolated Supabase project/config was found; real Auth/PostgREST/Storage lifecycle and races are BLOCKED. Actual production metadata has private medication-sources with null MIME/size restrictions and broad owner Storage UPDATE/DELETE, which does not enforce protected-source retention. Review a bounded Storage policy design compatible with enrollment/draft cleanup, parser/scanner/quota needs, durable cleanup and object backup/restore before a real-user deletion/upload release. New writes/schema/policies and production execution require separate specific approval.
- Supabase CLI ledger is absent; only core_schema_migrations is authoritative. Unscoped db push can replay old migrations and include unrelated032/033. Use a reviewed scoped runner only after readiness/approval; its DDL-to-ledger failure window also needs review. Keep031 separate from Today/Care Task032/033 release and preserve effective correction reads after033 exists.
- Verification: final focused backend230 PASS; affected Vitest49 PASS; browser gallery/history9 PASS plus PDF original workflow1 PASS (mock Auth/HTTP); TS/lint/build/scoped Ruff/format/diff checks PASS. Full Vitest has302 PASS/2 FAIL/1 uncaught error due stale App/Care Task tests owned by the concurrent work; not erased, weakened or labelled PASS. No live-device or authenticated Storage claim.
- Detailed release/rollback plan, free isolated test-project owner steps, offline target guard and exact modified files: docs/MEDICATION_LIBRARY_RELEASE_READINESS.md. No stage/commit/push/merge/deploy, production schema-cache reload, migration, patient write or Storage change was performed. Existing changes and earlier ledger evidence are retained.


### 2026-10-19 Today/Care续接验收补充（保留MT-CARE-03原风险与授权边界）

本地完成默认3条可展开未记录清单、窗口说明、033关闭态不请求/不伪空、032独立能力开关及旧RPC字段丢失保护、Postgres/worker旧Schema兼容、异常旧年份二次核对和原前端回归修复。完整前端308通过，最后时间线保护定向13通过；相关后端95通过及新增保护1通过；真实SQL12通过+新增拒绝3通过（依赖测试加强复验1为重叠）；真实Chrome/React/本地FastAPI五个不同流程通过，模拟Auth/合成内存，非真实通知。原302/2失败/uncaught证据已被本次修复后的结果替代，历史记录保留。

032/033本地契约GO，生产执行/启用NO-GO待独立批准/备份/托管联合验收；031独立NO-GO，不捆绑。027–030未重复，生产未修改。ENABLE_CARE_TASK_FOLLOWUPS、ENABLE_LATE_DOSE_REPORTS、ENABLE_MEDICATION_LIBRARY_FILES默认false且互不启用；已有033报告后不得退回忽略更正的原始事件读取。真实Push及手机原生控件/辅助技术NOT VERIFIED。详见本地status/TODAY_CARE_TASKS_20261019.md续接A–G；后续日历边界见CARE_CALENDAR_INTEGRATION.md。本补充不授权生产、Git或扩大Agent历史写入。

### 2026-10-19 集成RC补充：MED-LIBRARY-01 / MT-CARE-03发布门与现有Agent回归

保持原ID、风险及独立授权门，详见[INTEGRATED_RELEASE_CANDIDATE](INTEGRATED_RELEASE_CANDIDATE.md)。新增证据：实际030 API/SQL/RLS/worker + compatibility19通过，031 SQL26、032/033 SQL15、前端309、Chrome16不同流程通过；完整后端1112通过/1失败/119跳过。已修复active但计划结束日在过去的药物在Current/History两边消失的展示缺陷，无临床状态写入。当前剩余Agent ScenarioA第17步RESTORE后的指代恢复失败，返回选药澄清而未读取知识；精确上下文丢失原因未确认，本轮未改Agent runtime。该失败及未隔离source artifact/未知托管SHA阻止完整RC宣称GO。

新增发布工具限制：032/033 SQL可独立，但现有--only先校验所有更早编号ledger，031未应用时会拒绝032/033（2个拒绝分支测试通过，无DDL/ledger写入）。独立发布须先审查有明确依赖/hash/失败恢复的runner或operator方案；不授权修改生产ledger，不为解锁032/033捆绑未验收031。旧DDL提交后ledger登记的失败窗口也仍需处理。

可推进的3项：①核实托管baseline并处理剩余RESTORE回归，再经Git授权隔离A并重验；②owner创建/指定隔离Supabase配置，完成真实Auth/Storage/RLS/清理恢复验证；③审查独立迁移执行与恢复方案。真实Push/设备、PDF安全及持久orphan reconciliation门保持未完成；不是用mock或裸PostgreSQL关闭这些门。所有生产/Git/部署操作仍需单独明确授权。

### 2026-10-19 follow-up: Agent RESTORE regression resolved locally

The Scenario A turn-17 failure was reproduced. RESTORE deliberately repopulates bounded recent text but does not restore trusted product IDs. In `ReadDialogue`, historical product recovery used ingredient-inclusive matching without applying the mentioned strength, so “Amlodipine 10 mg” matched both current Amlodipine strengths and triggered a new choice. The bounded repair resolves each restored turn through the current medication tool result, including strength, accepts only a single product match, and stops at a multi-product match so older history cannot override ambiguity. Added direct regression coverage for exact 10 mg knowledge read and ingredient-only clarification. Targeted scenario/tests:3 passed; Agent suite:135 passed/25 opt-in skipped; full backend:1117 passed/120 opt-in skipped. Local deterministic/stub evidence only; real Gemini/hosted behavior remains NOT VERIFIED. No API/DTO, migration, flag, Storage or Release A compatibility change; no database operation. Production Release A NO-GO, deployed baseline/source binding still outstanding. This satisfies only the local RESTORE regression; it does not close unrelated release gates.

### 2026-10-19 MED-LIBRARY-01：已登录诊断误报修正与Auth证据边界

旧脚本扫描多个SDK样式key并自行检查expires_at，会将无关key或SDK续期前快照误判为未登录；这不证明用户已登出。已改为仅localhost:5173的Vite开发入口，复用同一SDK及请求封装、无匿名bootstrap、只GET计数/被动观察既有Today/Alerts；安全聚合输出、并发去重、生产入口删除均已本地验证。另修复Auth verifier将身份服务超时/网络/5xx误映射401的问题；这些现映射503，不放宽token校验或RLS。前端317、后端相关110、Chrome模拟Auth/API三流程通过；不冒充真实用户认证验收。保留历史patient counts未验证状态：须由用户在原登录页面运行修正脚本取得摘要，具体既往401/503原因仍NOT VERIFIED，未建立刷新竞争或项目错配结论。详见[AUTHENTICATED_BROWSER_DIAGNOSTIC](AUTHENTICATED_BROWSER_DIAGNOSTIC.md)。本轮没有生产、Git、迁移、Storage/RLS或其他页面变更，不关闭既有Release A/B门。


### 2026-10-19 owner-approved Regimen Records supplement

The earlier terminal-history-only display is superseded: default All Courses includes active and terminal confirmed supersedes_id chains; Currently Tracked and Ended filters preserve lifecycle truth. Gallery no longer calls an active elapsed-date plan historical; patient-local warning explains it remains tracked. No lifecycle/database/dose/migration writes. Related local acceptance and commit scope: [REGIMEN_RECORDS_UX](REGIMEN_RECORDS_UX.md). Synthetic component/backend/browser evidence is separate from production verification.


### 2026-10-19 final unified local integration and categorized commits

Owner authorized selective local commits only; existing Regimen Records commit7b2d478 is preserved. Foundation2c1acfe and unified application bf3331a are local snapshots, not production GO. Final acceptance and exact manifests: [LOCAL_INTEGRATION_VERIFICATION](LOCAL_INTEGRATION_VERIFICATION.md). Full backend1129 PASS/128 opt-in SKIP; frontend319 PASS; real isolated PostgreSQL53 distinct cases;23 distinct synthetic Chrome journeys PASS. Old History names/counts, hidden mounted-row locator, missing Files fixture, accessible-name/unsaved-exit expectations and Summary standalone-number expectation are resolved without relaxing consent or lifecycle safety. Migration runner now commits reviewed DDL and ledger atomically, preserving exact hashes and ordered031 -> 032 -> 033 prerequisites; actual rollback-on-ledger-failure/concurrency tests pass.

Real Supabase Auth/PostgREST/Storage remains BLOCKED; PDF parsing/scanning, protected-source Storage retention, orphan reconciliation/restore and cross-service race acceptance remain release gates, with existing IDs/risk/approval requirements unchanged. No production migrations, data/Storage/RLS/config changes, Push or deployment were executed. The previous separate schema030 Release A plan is superseded by owner instruction; compatibility tests are retained as regression coverage, not a separate release. Commit/push authorization never grants production migration or capability enablement.


### 2026-10-19 production migrations031-033 applied with explicit owner approval

Owner approved only the exact production schema operation for Supabase project `wteaeubvgmheqetmjbml`, database `postgres`, session pooler5432. Immediate read-only recheck confirmed all30 prerequisite ledger hashes, pending031-033 and absent target objects. The committed scoped transactional runner applied031,032,033 once in order, each returncode0; no rollback or retry occurred. Production ledger now has33 exact matching hashes. Post-verification at2026-10-19T12:43:13Z confirmed13 function bodies match reviewed SQL, four new tables have forced owner RLS, eight file/late-report RPC ACLs reject anon/service_role, effective view is security_invoker, three new triggers enabled, and no invalid indexes/unvalidated new-table constraints. Authenticated zero-row read smoke passed; no patient rows were read or business RPCs invoked.

Migration032 preserves existing Care Task RPC grants: create/update remain executable by service_role as well as authenticated; anon is denied. This is retained existing ACL, not a new grant or an authorized follow-up privilege change. The first postcheck wrongly expected that inherited permission to be absent (and expected audit immutability triggers not defined by031); metadata diagnosis corrected the verification harness to the actual SQL design. No migration rerun, privilege repair or patient write was performed. Audit direct DML is denied through grants/RLS; actual production audit/write behavior was not exercised.

Evidence (ignored/private): outputs/release/production031-033-execution-20261019.json and production031-033-postverify-20261019.json. Earlier pending-production statements are historical and superseded for schema application only. Backend/frontend/worker code was NOT deployed; flags unchanged; real Auth/Storage and hosted feature acceptance remain unverified/blocked separately. No Push, Storage policy/object change, patient business writes or production test records. The only production changes were the reviewed migration SQL and its ledger records. Acceptance documentation updated locally, not committed.


### 2026-10-19 local migrated-feature activation and course-boundary supplement

The owner supersedes the earlier active-but-elapsed display: derive expired/ended presentation from explicit patient-local course dates without lifecycle writes. Add Medication is above the current list. Local031-033 flags enabled; committed defaults remain false. Owner-authenticated browser evidence: Medications200/item_count5, Regimens200, Today200, Alerts200; all Authorization-attached, failure_stage none, diagnostic complete. The reproduced post-restart503 was a restricted API process network failure (Windows10013; same Auth read200 outside restriction), not proof of logout or missing schema. Owner resumed the normal launcher after the agent released8001. Do not repeat old Auth/port investigations without new evidence.

Care form alignment/direct modal, advance reminders, fixed original Snooze deadline, Today visibility, course classification and calendar/task-reminder integration are implemented locally. New034 supports optional multiple reminders without altering032:32 related isolated PostgreSQL cases pass (13 multiple/Worker,4 successor,15 Today/Care), including queue expiry/dedup, RLS/version/audit and rollback guard.034 is not applied to production and requires separate approval plus coordinated API/Worker capability enablement. After multiple schedules exist, preserve that reader/Worker; use reviewed forward fixes rather than disabling or destructive rollback.

Actual real Supabase Auth/Storage file lifecycle/recovery and closed-browser Push receipt remain blocked/unverified. Cross-tab presentation leasing is best effort for simultaneous claims, not distributed exactly-once delivery. Full behavior matrix, tests, limitations and rollout gates: [FEATURE_ACTIVATION_20261019](FEATURE_ACTIVATION_20261019.md). No031-033 replay, new production DDL, patient/Storage writes, hosted configuration, Push or deployment.


### 2026-10-19 Migration034 production-order compatibility blocker

Owner requested a narrow034 approval precheck, with no deployment or execution before explicit final approval. Condition1 FAIL / EVIDENCE CONFLICT with any inferred migration-before-old-application safety: pre034 CareDTO uses extra="forbid"; SupabaseCareRepository.tasks validates full table rows, and create/update RPCs return to_jsonb(result).034 adds reminder_offsets even when NULL, and future RPC histories contain that field. A synthetic in-memory probe using the exact5a1136b contract rejects the added nullable field with extra_forbidden; the matching current contract accepts it. Disabled multiple-reminder flags only change writes/Worker query selection, not database row shape. Thus old DTO Care Task reads/RPC responses can fail before enabling the feature. No deployed SHA is inferred from local HEAD; the existing pre034 contract is demonstrably incompatible, so condition1 cannot be confirmed without establishing a compatible deployed reader.

Conditions2/3 structurally pass: nullable/no-default column, no top-level patient DML/backfill/delete, retained scalar reminder and existing ACL/RLS; function DML executes only on later business calls. Condition4 passes code inspection: scripts/db.py migrate --only202610190034 selects one target, validates earlier hashes, and apply_recorded_migration commits reviewed DDL+ledger under the transaction lock. No full tests or production access were repeated.

NO-GO for the requested schema-first order. Minimum safe correction is an independently approved deployment of the existing compatible CareTask/TaskHistory readers and Worker with ENABLE_MULTIPLE_CARE_REMINDERS=false, verified on the current033 schema, before applying034. Alternatively separately review a compatibility release design. Owner explicitly prohibited deployment in this operation; none was performed. No034 execution, production read/write, Storage operation, feature flag change, Git staging/commit/Push or unrelated worktree edit.034 remains pending. Do not request execution approval until this concrete ordering blocker is resolved.
