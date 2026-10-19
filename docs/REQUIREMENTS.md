# MediThread Requirement Register

审查日期：2026-10-18，Asia/Singapore。基线：`feat/agentic-ux-landscape` / `f664c5b` 加现有未提交工作树。

**这是已知来源范围内的需求追溯，不是全部聊天已读或全项目验收完成声明。** 产品规范继续使用 [MASTER_SPEC](MASTER_SPEC.md)，批准/暂缓门槛继续使用 [DEFERRED_WORK](DEFERRED_WORK.md)，不替换 `BUILD_PLAN.md` / `status/tasks.json` 的历史ID。本文登记行为和证据，[缺口与执行计划](REQUIREMENT_GAPS.md)负责排优先级，[持续验收规则](REQUIREMENT_ACCEPTANCE.md)规定后续维护方式。

## 状态与证据规则

- 决策性质与实现/验收分开：APPROVED、COMPLETED CLAIM、PROPOSED、SUPERSEDED、REJECTED、UNKNOWN。COMPLETED CLAIM 是报告属性，不自动构成批准或 PASS。APPROVED 也不复活暂缓项的开发、生产或 Git 权限。
- 表内默认决策为 APPROVED，来源必须是可见 owner 要求、已保存正式 Prompt 或现行工程/产品规范；其他性质显式写出。只有助手建议、旧报告中的建议，不算批准。
- 验收为 PASS / PARTIAL / FAILED / NOT VERIFIED / BLOCKED / NOT IMPLEMENTED / SUPERSEDED。PASS **仅限证据栏所述路径、版本、环境**；生产独立列示。代码存在、模拟 HTTP、DEMO 内存、真实隔离 PostgreSQL、真实 Provider、生产、真机不能互相替代。
- **本轮唯一业务定向测试**：现有 `tests/backend/agent_patient_semantics_audit.py`，30 项，10 通过 / 20 失败，JUnit `outputs/requirements-agent-audit-20261018.xml`。仅DEMO内存fixture；过去日期风险用例只准备提议而未确认，无外部模型或生产请求。其他运行结果均标为历史证据，不伪称本轮重跑。
- 实现位置使用当前公开服务/组件路径；目录表示责任边界，非全库逐行证明。代码/测试存在本身最多证明实现线索。报告测试总数不是单条需求验收。
- 生产状态默认 **当前版本未核验**；“历史 live”只指带日期的既有证据。本轮不连接生产，不更新 Live SHA。

## 来源目录

### 可访问仓库资料

| 代号 | 来源 | 权威与限制 |
|---|---|---|
| S01 | `AGENTS.md`、[ARCHITECTURE](ARCHITECTURE.md) | owner 工程/安全/审批规则；本轮已读 |
| S02 | [MASTER_SPEC](MASTER_SPEC.md)、[WORKFLOW_SPEC](reference/WORKFLOW_SPEC_2026-10-12.md) | 产品基线；引用的144页原综合资料/竞赛截图未独立全量核对 |
| S03 | [BUILD_PLAN](BUILD_PLAN.md)、`status/tasks.json` | 旧任务与验收条目；任务表快照2026-10-16，不能作当前完成率 |
| S04 | [DECISION_LOG](DECISION_LOG.md) | Provider/范围的带日期替代决定，优先于旧设计 |
| S05 | `prompts/01_RECON_AND_CONTRACT_ASK.md`、`02_OVERNIGHT_BUILD_CRAFT.md`、`03A_STAGE2_CONTRACT_REFRESH.md`、`03_MORNING_INTEGRATION.md`、`04_FINAL_RELEASE_QA.md` | 已保存正式任务；本轮按相关章节检索，不宣称读过其他聊天 |
| S06 | [DEFERRED_WORK](DEFERRED_WORK.md)、`MediThread_Deferred_Work_Backlog_2026-10-17.md` | 当前门槛与原始背景分开；旧状态可能已被后文取代 |
| S07 | `outputs/AGENT_PATIENT_AUDIT_2026-10-17.md`、`tests/backend/agent_patient_semantics_audit.py` | 历史9通过/21失败；本轮重跑为10/20，结果不可混用 |
| S08 | [CHALLENGE_2_COVERAGE](CHALLENGE_2_COVERAGE.md)、[LONG_TERM_CARE](LONG_TERM_CARE.md)、`status/SESSION_05.md` | 早期合成/真实集成证据，非新版部署证明 |
| S09 | `status/UX_POLISH_C_20261018.md`、[CONVERSATIONS](CONVERSATIONS.md) | SQL/HTTP/浏览器续聊证据，明确 DEMO 模型与真机限制 |
| S10 | `status/RECORDS_NAMES_ENROLLMENT_20261018.md`、`RECORDS_SEARCH_REFINEMENT_20261018.md`、[RECORDS_HISTORY](RECORDS_HISTORY.md) | 同名浏览、搜索、日期、真实本地查询证据 |
| S11 | `status/RECORDS_CONFIRMED_DRAFTS_20261018.md` | confirmed-only 查询与取消/恢复/激活旅程 |
| S12 | `status/DRAFT_ENTRY_MANAGEMENT_20261018.md`、[DRAFT_DELETION_PROPOSAL](DRAFT_DELETION_PROPOSAL.md) | 最新本地删除/添加入口报告；有明确未完成边界 |
| S13 | `outputs/UX_POLISH_A1.md`、`RECORDS_FUNCTIONAL_COMPLETION.md` | 实际 UI 证据；旧 selected-plan 查询限制被新接口替代 |
| S14 | [RECORDS_INGREDIENT_GROUPING_PROPOSAL](RECORDS_INGREDIENT_GROUPING_PROPOSAL.md) | 权威成分归组方案；不再阻断已批准同名浏览 |
| S15 | [MEDICATION_KNOWLEDGE_SOURCES](MEDICATION_KNOWLEDGE_SOURCES.md)、`backend/MEDICATION_UNDERSTANDING.md` | openFDA 工具已存在；覆盖/匹配限制仍在，旧“完全缺知识工具”过时 |
| S16 | [STAGE2_V010_UPGRADE](STAGE2_V010_UPGRADE.md)、[STAGE2_API_GAPS](STAGE2_API_GAPS.md)、`docs/external/` | 当前接收契约与旧真实合成照片反馈；非所有 OCR 字段准确性证明 |
| S17 | `status/PUSH_ONE_SHOT_RESULT.md`、`WEB_PUSH_PRODUCTION_VERIFICATION.md`、[REMINDERS](REMINDERS.md) | 真实 one-shot processed=0，不证明设备送达/Cron开启 |
| S18 | [SUBMISSION](SUBMISSION.md)、`internal/PROJECT_BRIEF.md`、`status/MEDITHREAD_RC.md` | 提交草稿/owner 确认私有 Tencent 证据；不是平台 receipt |
| S19 | [DEPLOYMENT_CHECKLIST](DEPLOYMENT_CHECKLIST.md)、[DEVELOPMENT](DEVELOPMENT.md)、`deploy/` | 准备文档包含旧“未部署”描述，不代表今天没有线上系统 |
| S20 | `status/UNIFIED_ASSISTANT_UX.md`、`DRAFT_ABANDONMENT_PREFLIGHT.md`、Git history | 保留旧方案/完成声明，后续要求优先 |
| S21 | [WORKFLOWS](WORKFLOWS.md)、[DATA_MODEL](DATA_MODEL.md)、[SAFETY_AND_EVALUATION](SAFETY_AND_EVALUATION.md) | 原始复合意图、source/product/plan模型、具体安全验收ID；流程图含目标不全是已实现事实 |

### 本次上下文直接可见的 owner 要求

这些 U 索引是本轮可见对话的来源身份，**不声称有完整 ChatGPT 导出文件**。

- **U01**：Global Assistant Navigation & Full Chat Workspace：桌面主导航、Today 原位、手机完整页、共享状态、移除浮动入口。
- **U02**：Me & Records Alignment、UX Polish A 与 **A.1 FINAL**：最终暖白/容器/间距、自然高度、真实页面验收、Records 三模块；FINAL 替代旧零散要求。
- **U03**：UX Polish B、pytest/Git 政策：患者可读计划/四状态、健康/跟进表单；历史补记仅审查，撤销自动 Commit。
- **U04**：BUG-01 及 governance：患者文字/技术照片证据/历史分离，禁止擅改生产历史。
- **U05**：独立 Agent 反馈：未给药名先查；选择药名承接用途；23514 弹框；昨天查询；Amlodipine 用途答案不符合问题；开发热重载。
- **U06**：Records Functional Completion、Query & Grouping Correction：真实全部药物/计划/日期查询、排序、分页；不能用 Mock Preview 替代。
- **U07**：Medication Grouping & Search：最初要求可靠 ingredient 身份归组；后续 **U08** 明确同名先合一，不能继续将权威 ingredient 方案当浏览阻断。
- **U08**：截图补充：去“独立登记”；日期与天数自动计算；数量/单位/日期/时间基线；成功消息自动消失。
- **U09**：仅确认添加的药进 Records；草稿删除+确认+真删除；最新 SQL/触发器限制、退出清空、同期重复限制、编辑标记、添加长按钮/读取与手动直显、来源设置展开、裸药片入口。
- **U10**：UX Polish C：稳定 threads、续聊/恢复、草稿/异步回复/来源隔离、隐私、附件、真实SQL验收；必要生产026兼容迁移获具体授权，不等于应用部署许可。
- **U11**：本轮需求追溯：只审查/文档/必要定向检查，建立轻量行为级规范，不修业务、不清工作树。
- **U12**：旧清理请求被后续明确否决；不执行旧文件清理/无关 ignore/Git 操作。
- **U13 / 2026-10-18新增明确决定**：UX Polish C.1：宽屏默认展开历史、桌面选择后保持；窄屏选择后关闭；文字新对话在侧栏顶部；快捷任务与多行Composer同底区；短气泡自然宽、长回复限阅读行宽、quota不插消息；只改真实Workspace，不重做AG-06/API/026/Agent。
- **U14 / 2026-10-18 C.1 后续补充**：Today 内嵌 Assistant 在页面跳转后收起完整最近聊天（恢复记录与当前消息）；“查看今日用药”快捷入口定位到 Today 的今日用药区域。保留“了解药物”等原有 Agent 快捷任务。
- **U15 / 2026-10-18 Agent Correctness02**：明确批准一般用途可信来源、当前/历史/健康回答完整性、多轮指代、结构化药物按钮及自动继续、三组15–30轮与完整实际问答记录；不授权历史补记、生产028或部署。矩阵：`outputs/AGENT_CORRECTNESS02_ACCEPTANCE_20261018.md`；不将旧建议倒写成当时已批准。
- **U16 / 2026-10-18 Records实际反馈**：owner提供 `INVALID_INPUT / HTTP400 /42703` 与 `PROVIDER_UNAVAILABLE`，否决“目前的用药”区块及“上方仍显示目前用药”说明，指出重叠。**EVIDENCE CONFLICT**：旧本地UI兜底不证明实际查询修复。随后owner要求先续接C02；该Records修复保持未完成，不推测具体列名或自动Migration。
- **U17 / 2026-10-18 当前明确要求**：续接修复U16；定时剂次不应无限留在今日待处理，超时自动呈现未记录。落地规则：计划后2小时/下一次计划时点/患者本地午夜取较早值，只派生展示，不自动制造“自述未服”事件；PRN不制造每日必服剂次。矩阵/直接SQL与浏览器证据见 `status/RECORDS_TODAY_ACCEPTANCE_20261018.md`；本地实现PASS scoped，生产未验。U16历史说明保留，当前本地缺口由该报告更新。
- **U18 / 2026-10-18 新增明确要求**：间隔用药缺少起点时，程序与Agent主动询问首次时间，明确“留空默认08:00”，不能静默猜测或自动激活。本地新增首次日期/时间与默认来源标记，沿用原来源核对和患者确认；不批量修改既有计划或服药事件。实现与验收边界见 `status/INTERVAL_FIRST_DOSE_20261018.md`；真实Gemini及生产未验。

## 行为级需求

每行保留：唯一ID、领域、具体预期、来源/变化、优先级、实现位置与状态、直接验收证据、生产层、缺口/建议。没有列成独立开发阶段；缺口复用原 BUG/REC/DB/AG ID。

### 工程与基础安全

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-ENG-01 / P0 | typed public boundaries、DI、Agent不写SQL、前端业务只走FastAPI；S01/S05 | EXISTS；`backend/app/contracts/`、`transport/container.py`、`frontend/src/api/client.ts` | PARTIAL：结构测试/公开边界存在，本轮非全库依赖审计 | 当前发布未核验；跨组件修改时定向约束 |
| MT-ENG-02 / P0 | 版本化SQL、患者RLS/复合FK/事务幂等/私有附件；S01/S03 | EXISTS；`supabase/migrations/`、`tests/test_migrations.py` | PARTIAL：旧真实隔离/025/026证据，027真实隔离PG；不是所有新链路生产验收 | 001–026有带日期证据，027未上生产 |
| MT-ENG-03 / P0 | 无明确授权不Stage/Commit/Deploy/生产写；保留既有修改；U03/U11 | IN FORCE；`AGENTS.md` | PASS：本轮仅只读Git/文档/本地语义测试，无索引或生产操作 | 每轮持续执行；旧自动提交授权失效 |
| MT-ENG-04 / P2 | 隔离Python测试依赖；本地开发默认重载，不改生产；U03/U05/S19 | IMPLEMENTED；`scripts/start_dev.py`、`tests/test_start_dev.py` | PASS：台账有Windows真实合成reload smoke；本轮复用pharmascan-care | 仅开发；env/launcher/依赖变化仍需重启，不必重做 |
| MT-SAFE-01 / P0 | visual/intake独立、PRN/无图、一次确认/重试幂等、未记录≠漏服；S01/S02 | IMPLEMENTED；`application/dosing.py`、`domain/policy.py` | PARTIAL：旧B14真实证据、本轮PRN/未知状态安全用例；过去日期提议仍失败 | 不能由底层安全测试推定所有自然语言写提议安全；见MT-AGENT-06 |
| MT-SAFE-02 / P0 | owner来自验证token，跨患者药物/session/thread/附件拒绝；S01/U10 | IMPLEMENTED；`transport/`、RLS migrations、`test_auth_boundary.py` | PARTIAL：旧真实JWT/RLS，026/027隔离SQL；新路径覆盖有限 | 当前生产未重查；禁止放宽RLS |
| MT-SAFE-03 / P0 | 历史补记仅审查event_time/due_at/created_at、库存、幂等；U03/S06 DB-01/02/03 | REVIEW ONLY；`DOSE_BACKFILL_PROPOSAL.md` | BLOCKED：明确没有写实现许可；已结束/已替代和更正分别审批 | 不因用户说“昨天”就新增补记，不与BUG-04防误写混同 |
| MT-SAFE-04 / P0 | 无诊断/处方调整/吞服证明/视觉安全结论/虚构医生通知；S01/S02 | IMPLEMENTED scoped；`domain/policy.py` | PARTIAL：策略/负例存在，非穷尽真实模型输出证明 | 研究原型；临床/监管验证不能由测试替代 |
| MT-SAFE-05 / P0 | DDI/重复成分筛查需许可与可靠覆盖，空alert≠安全；S01/S02 K002/S15 | DISABLED；`MEDICATION_KNOWLEDGE_SOURCES.md` | BLOCKED：已有unknown误映射/许可边界，不启用患者筛查 | 不是“已完成DDI”；具体安全/许可/授权前继续暂缓 |
| MT-SAFE-06 / P0 | 上传签名/MIME/尺寸/像素/私有访问与注入边界；S01 | EXISTS；`transport/`、`contracts/chat_photo.py` | PARTIAL：上传及BUG01负例；本轮未重新全链审计 | 外部留存未核验，不承诺自动PII消除/零留存 |

### Medication Enrollment / 来源 / 计划

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-ENR-01 / P0 | 手动来源→核对→独立确认才激活；缺字段不推断；S02/S05/U03 | IMPLEMENTED；`application/enrollment.py`、`EnrollScreen.tsx` | PASS：S11取消/resume/确认真实本地浏览器，review/challenge测试 | 新UI仅本地；不重复实现 |
| MT-ENR-02 / P0 | 产品规格、每次量/单位、患者登记、来源、regimen版本分离；S01/U03/U08 | IMPLEMENTED；`contracts/dto.py`、core SQL | PARTIAL：schema/typed DTO+S10标签/规格测试 | 真实多规格来源映射需provider验收；version≠疗程 |
| MT-ENR-03 / P1 | 药盒/标签/处方读取保原始证据，缺失冲突可补充；S05/S16/U09 | IMPLEMENTED；`evidence_enrollment.py`、`EvidenceEnrollmentScreen.tsx` | PARTIAL：旧live合成OCR+当前本地路由；非当前完整照片集 | 中文/条件指示和实际识别仍待验 |
| MT-ENR-04 / P1 | 早期场景中的PDF患者端完整导入；S02/S05 | NOT IMPLEMENTED；`source_preview.py`现图片路径 | BLOCKED：S08/S16明确应用PDF链路未完成，手动fallback不是PDF完成 | 确认是否仍保留当前产品scope；不能以资料缺失推无实现 |
| MT-ENR-05 / P0 | 编辑保留原扫描证据/历史，新计划版本可追溯；S01/U09 | PARTIAL；`enrollment.py`、`evidence_enrollment.py` | PARTIAL：版本/source约束及新patient_edited；不是完整字段差异审计 | 027 marker仅本地；不回填旧记录 |
| MT-ENR-06 / P1 | 开始日+天数或最后日二选一，含首尾自动计算；U08/S10 | IMPLEMENTED；`EnrollScreen.tsx` | PASS：S10真实App/API+闰年/同日/反向日期测试，`enrollment-refinement.spec.ts` | 本地；无需重做 |
| MT-ENR-07 / P2 | 数量/单位、开始/结束日期、每日时间控件基线对齐；U08/S10 | IMPLEMENTED；`ui/components.css`、`EnrollScreen.tsx` | PASS：S10 DOM几何/截图+窄屏150% | 真实设备原生控件待验 |
| MT-ENR-08 / P2 | 成功消息自动渐隐，无需关闭；错误/确认不自动消失；U08/S10 | IMPLEMENTED；`primitives.tsx` | PASS：AutoDismissNotice timer及浏览器4.5秒、reduced-motion | 本地；无新证据不重做 |
| MT-ENR-09 / P1 | 离开手动添加先确认；退出清空未保存表单、取消保留；U09/S12 | IMPLEMENTED；`navigation.ts`、`App.tsx`、`EnrollScreen.tsx` | PASS scoped：`medication-entry-management.spec.ts`实际tab退出/重新进入 | browser关闭/后退不等同已验；已保存草稿另外管理 |
| MT-ENR-10 / P0 | 待核对药不进入Records，来源核对≠确认添加；U09/S11 | IMPLEMENTED；`application/record_history.py` | PASS：直接ID/pending异常时点负例及取消→resume→激活实际旅程 | 新查询仅本地；ended/superseded已确认历史继续保留 |
| MT-ENR-11 / P1 | 删除草稿取消/二次确认+真实专属数据清理，不假成功；U09/S12 | PARTIAL；`application/draft_deletion.py`、`PendingEvidenceTasks.tsx` | BLOCKED scoped：纯草稿真实SQL/HTTP/browser通过，audit-linked原子拒绝 | **不是所有草稿可删**；DB-06需审计引用保留方案，不能泛称完成 |
| MT-ENR-12 / P0 | 去DELETE全面触发限制，改SQL权限/原子RPC；U09/S12 | IMPLEMENTED LOCAL；`202610180027_draft_deletion.sql` | PASS：6真实隔离PG覆盖权限/owner/并发/confirmed/overlap；I/U守卫保留 | 027生产NOT RUN，rollback文件未执行，不宣称生产可删 |
| MT-ENR-13 / P1 | 图片实际Storage删除、失败明确并可重试；U09/S12 | PARTIAL；`infrastructure/draft_deletion.py` | PARTIAL：durable receipt+MockTransport真实请求构造；当前页retry | live Storage未验；刷新后无pending-cleanup列表，不能仅删metadata称文件删除 |
| MT-ENR-14 / P0 | 同期同药不能重复确认添加，引导现有药修改；U09/S12 | IMPLEMENTED scoped；`enrollment.py`、migration025 | PARTIAL：旧真实并发+027实际overlap守卫；多个pending仍可能存在 | 025有生产历史证据；Agent audit REGIMEN_OVERLAP另BUG-06未解 |
| MT-ENR-15 / P1 | 从我的药物修改时间等，尤其扫描来源显著标“编辑过”；U09/S12 | PARTIAL；`enrollment.py`、`MedicinesHub.tsx`、`historyFilterLabels.ts` | PARTIAL：新marker持久化测试；未证明完整现行计划编辑旅程 | 仍须停止旧计划再核对新版本，无一键替换；UI标记不等于全部编辑需求满足 |
| MT-ENR-16 / P2 | 长添加按钮在管理入口上方，下方直接读取/手动两方式；U09/S12 | IMPLEMENTED；`MedicinesHub.tsx` | PASS：真实Chrome390/768/1280/1920位置/宽度截图 | 本地；旧add-method路由仅兼容 |
| MT-ENR-17 / P1 | 关联已有药物与自动照片分类设置展开；U09/S12 | IMPLEMENTED；`EvidenceEnrollmentScreen.tsx` | PASS：真实DOM可见且不在details中 | 本地；不代表分类准确性 |
| MT-ENR-18 / P1 | 有裸药片来源选项，接既有模型路径，不作OCR文档；U09/S12 | IMPLEMENTED routing；`EvidenceEnrollmentScreen.tsx`、`VisualCheckScreen.tsx` | PARTIAL：实际视觉页/API503显式模拟，不是识别成功 | 真实Stage2候选/图像效果待验 |

### Records 查询 / 归组 / 分页

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-REC-01 / P1 | 我的用药记录，默认全部药物/相关计划/30天；U06/S10 | IMPLEMENTED；`HistoryScreen.tsx` | PASS：真实React→localFastAPI默认目录/请求；不是示意板 | 新路径本地 |
| MT-REC-02 / P1 | 同名顶层一次，差异移入计划，去UUID/独立登记；U07→U08/S10 | IMPLEMENTED；`historyFilterLabels.ts`、`record_history.py` | PASS：exact normalized name组和两登记真实本地聚合；原ID保留 | 不推成分等价，不模糊合别名，不合并数据库记录 |
| MT-REC-03 / P1 | 权威同成分跨规格/剂型归组；U07→U08/S14；**PROPOSED residual scope** | NOT IMPLEMENTED；core SQL仅ingredient_names文本，无可信Ingredient ID关系 | BLOCKED：最初可信成分要求未完成；U08已改浏览目标，不能再阻断MT-REC-02 | 成分映射仅独立方案/待需求确认，不自动补Schema/回填 |
| MT-REC-04 / P1 | 药名搜索/清空/全部/键盘/中英/移动；U07/S10 | IMPLEMENTED；`HistoryScreen.tsx` | PASS：真实输入+native select键盘/搜索/clear，HistoryFilters | 不是复杂Combobox已复用声明；真机键盘另验 |
| MT-REC-05 / P1 | 组默认全部相关计划，按可靠ID可缩小到具体计划；U06/U08 | IMPLEMENTED；`record_history.py`、`HistoryScreen.tsx` | PASS：S10跨登记27条/指定计划20条、本地API/cursor/foreign负例 | 元数据2000、scope100计划上限，不声称无限 |
| MT-REC-06 / P1 | 计划标签明确规格/每次量/单位/频率/真实生效结束状态，不重复长说明；U03/U06/U07 | IMPLEMENTED；`historyFilterLabels.ts` | PASS：标签测试/真实select；不编造结束日，缺字段明确未知 | 本地 |
| MT-REC-07 / P1 | 生效时间降序、稳定次序，不以active/created/version排序；U06 | IMPLEMENTED；`HistoryScreen.tsx` | PASS：生效/创建颠倒fixture；当前UI同日ID降序稳定 | 旧报告称ID升序，当前方向变但稳定；非排序主需求失败 |
| MT-REC-08 / P1 | 7/30/90/自定义/全部已有历史/指定计划生效期真实查询；U06 | IMPLEMENTED；`patient_records.py`、`record_history.py` | PARTIAL：真实local API和PostgREST契约mock；新生产链路未验 | all只已有存储行，不重建旧计划；超界显式失败，不无界加载 |
| MT-REC-09 / P0 | 服药时点倒序；due_at/event_time与created_at提交时间区分；U06 | IMPLEMENTED；`record_history.py` | PASS：晚提交/双流keyset/sort_time/submitted_at合成负例 | event_time既有写入可能是报告时间，非吞服证明 |
| MT-REC-10 / P0 | 未来不混历史，四intake状态分开，未记录非漏服；U03/U06 | IMPLEMENTED；`record_history.py`、`HistoryScreen.tsx` | PASS：future cutoff/state负例和患者标签 | 不能因此关闭Agent旧日期/渲染BUG-05/08 |
| MT-REC-11 / P0 | 患者本地日期/含结束日/跨午夜边界；U06 | IMPLEMENTED；`record_history.py`、`HistoryScreen.tsx` | PASS：local→exclusive next midnight UTC、timezone fixture | 真实生产患者时区/DST旅程未验 |
| MT-REC-12 / P1 | 默认5条，真实next_cursor才更多，切过滤重置/防旧响应覆盖；U06 | IMPLEMENTED；`HistoryScreen.tsx` | PASS：0/1/5/6/20、cursor范围/双流分页/旧请求及实际浏览器 | 无假更多、非一次无界加载；生产PostgREST仍待验 |
| MT-REC-13 / P0 | 只读查询不物化计划、不写dose/库存、不越权；U06/S01 | IMPLEMENTED；`infrastructure/record_history.py` | PARTIAL：local snapshot/owned query/contract负例 | 旧dose-history GET可物化，不拿它假验新版只读查询 |

### Account / Inventory

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-AUTH-01 / P0 | Guest/email登录/资料/退出明确，换owner清状态；S02/S06/U02 | IMPLEMENTED；`frontend/src/api/auth.ts`、`App.tsx` | PARTIAL：SDK模拟/账户UI；updateUser/OTP/password路径存在 | 当前真实邮箱/hosted生命周期未验；不能用模拟SDK证明收邮件 |
| MT-AUTH-02 / P0 | Guest绑定邮箱保UID/药物/附件；登录已有账号不自动合并；S06 AUTH-01 | EXISTS；`api/auth.ts` | NOT VERIFIED：link调用updateUser/email_change与login分开；缺真实A/B升级证明 | 独立匿名升级/Storage/RLS验收；无自动迁移或合并授权 |
| MT-AUTH-03 / P0 | Try Demo独立匿名授权/合成资料，不共用稳定患者；S02/S03/S08 | EXISTS；`api/auth.ts`、`transport/container.py` | PARTIAL：旧synthetic JWT/RLS；正式profile不启用不安全memory demo | 当前无痕新用户hosted旅程未验 |
| MT-INV-01 / P0 | 未知≠0，标签数量≠实点，mg不转片数；S01/S08 | IMPLEMENTED；`domain/inventory.py`、`InventoryPanel.tsx` | PASS scoped：历史live合成库存+本轮unknown/estimate语义项通过 | 当前新UI上线后抽验；不重复开发 |
| MT-INV-02 / P0 | 实点/补药/纠正幂等保流水，已服才估算扣减；S01/S08 | IMPLEMENTED；`application/long_term.py`、migrations022/023 | PARTIAL：`test_long_term_care/live`历史真实owned ledger | 历史补记影响仍DB-01前置；不把估算说成物理库存 |
| MT-INV-03 / P1 | 首次登记一并填初始库存，处理激活/库存部分失败；S06 DB-04 | NOT IMPLEMENTED；`EnrollScreen.tsx`无stock输入，已有独立InventoryPanel | NOT IMPLEMENTED：独立库存存在不等于登记联动 | 已提出但暂缓写整合；单位/幂等/失败方案后具体授权 |
| MT-INV-04 / P1 | 低库存生成可核查跟进，不自动订药/通知药房；S01/S08 | IMPLEMENTED；`long_term.py` | PARTIAL：旧live task projection/idempotency证据 | reconciliation失败retry已有语义，不承诺药房收到 |

### Assistant Workspace / Conversation

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-ASST-01 / P1 | 桌面独立主导航完整Workspace，手机可见入口并保四底栏；U01/U10 | IMPLEMENTED；`App.tsx`、`ConversationSurface.tsx` | PASS：`1d9cba4`及后续实际App导航/七宽度S09 | 最新应用版本部署未核验 |
| MT-ASST-02 / P1 | Today直接输入/原位回复，只主动展开才导航，状态共用；U01/U10 | IMPLEMENTED；`AssistantScreen.tsx`、`App.tsx` | PASS：同mounted screen，本地实际HTTP/SQL状态/草稿/照片旅程 | 原生语音/真机另验，不建第二聊天系统 |
| MT-ASST-03 / P2 | 移除浮动Launcher，全局不弹右Drawer；U01 | IMPLEMENTED；`App.tsx`、`ConversationSurface.tsx` | PASS：真实导航；保留通用overlay分支不等于全局在用 | 未另维护上下文聊天，不能为旧Drawer重开同步项目 |
| MT-CHAT-01 / P0 | 稳定owned ID，同日A/B独立/跨午夜不拆/无大量空thread；U10 | IMPLEMENTED；`conversation_threads.py`、migration026 | PASS：S09真实SQL/HTTP/browser A/B/clock/first-send | 026有生产Schema证据，应用新版未核验 |
| MT-CHAT-02 / P1 | 选旧thread读真历史并向原ID追加，刷新/重进恢复；U10 | IMPLEMENTED；`conversation_threads.py`、`AssistantScreen.tsx` | PASS local：React→HTTP→真实隔离PG，DEMO stateless model验证上下文 | 不等于旧完整Agent执行Session；真实Gemini续聊待验 |
| MT-CHAT-03 / P0 | 有界恢复语境，旧事实/工具/确认不当当前权限，药物重查；U10/S01 | IMPLEMENTED；`conversation_threads.py`、`context_bounds.py` | PARTIAL：6turn/16KB/旧确认不恢复的SQL/HTTP/DEMO测试 | 真实Gemini各种指代/旧药物变更负例未验，禁止重放写入 |
| MT-CHAT-04 / P0 | 草稿/附件/异步回复/来源按thread隔离，切Today不新建；U10 | IMPLEMENTED；`AssistantScreen.tsx` | PASS local：`ConversationThreads.test.tsx`及S09实际A/B草稿/归属旅程 | 草稿仅内存，不承诺刷新/跨设备草稿恢复 |
| MT-CHAT-05 / P1 | activity排序、日期仅视觉分组，选后可续聊；U01/U10 | IMPLEMENTED；`ConversationHistoryBrowser.tsx`、`ConversationHistory.tsx` | PASS local：真实SQL历史、owned threads与legacy分开 | legacy日期组不得伪称连续会话 |
| MT-CHAT-06 / P1 | 桌面默认展开/选择后保持，可收起释放宽度；手机单视图选择后关闭；U01/U10→U13新增明确决定 | IMPLEMENTED LOCAL；`ConversationSurface.tsx`、`AssistantScreen.tsx` | PASS local：C.1实际App→本地API，28组合、A/B/切换/宽度实测；`workspace-layout.spec.ts` | 未Commit/Push/Deploy；真实设备键盘未验。MS-03现有来源已由U13解决，不倒写旧批准历史 |
| MT-CHAT-07 / P0 | 无可信thread的旧消息保留只读，不按日期回填/重写；U10 | IMPLEMENTED；history service/legacy browser | PASS：S09 legacy rows不变，026结果legacy_rows_unchanged=true | 旧照片污染处置另批，不借恢复清洗 |
| MT-CHAT-08 / P0 | 开保存才持久化；关保存不建thread，不许承诺临时跨设备恢复；U10/S01 | IMPLEMENTED；`conversation_threads.py`、`routes/agent.py` | PASS：save-off无thread/turn/claim负例和visible notice | hosted开关待验；临时runtime context与durable history分开 |
| MT-CHAT-09 / P1 | 持久化并恢复已授权附件引用，而非只正文/内部JSON；U10 | PARTIAL；`contracts/conversation_threads.py`、`AssistantScreen.tsx` | PARTIAL：目前仅photo_attached presence；S09明确不保存原图/预览 | 已批准附件关联仅做presence，持久恢复未实现；需Storage引用/撤销/隐私方案 |
| MT-CHAT-10 / P0 | 完整历史与context裁剪分开，中文UTF8/DB预算不靠删历史解决；U10/S06 BUG-07 | IMPLEMENTED；`contracts/context_bounds.py` | PASS scoped：本轮原长中文失败项通过；S09真实SQL恢复预算证据 | BUG-07局部通过，不关闭BUG-04–09整组 |
| MT-CHAT-11 / P0 | 药物/记录来源可靠、可返回、不猜MedicationID、不串thread；U10 | IMPLEMENTED scoped；`assistant_navigation.py`、`navigation_context.py` | PARTIAL：owned stable-ID服务，S09实际药物来源/返回 | 全部Medicines/Records入口未逐个直接验；页面文字非临床身份验证 |
| MT-CHAT-12 / P1 | 了解药物/记录/复诊快捷项作用于当前thread，不假自动分析；U10 | IMPLEMENTED；`AssistantScreen.tsx` | PASS：S09 prefill/no-autosend/shared composer | 知识答案正确性BUG-09不因快捷按钮通过而关闭 |
| MT-CHAT-13 / P1 | Quick Tasks紧靠Composer上方，同一底区8–12px；timeline独立滚动、quota在底区；U13 | IMPLEMENTED LOCAL；`AssistantScreen.tsx`、`ui/app.css` | PASS local：28组合DOM/间距，长消息不挤输入；quota组件负例 | 规则不改变Agent快捷任务内容；旧历史只读不显示任务/输入 |
| MT-CHAT-14 / P1 | 短患者气泡自然收缩靠右，长消息换行；助手最大760px可读宽；U13 | IMPLEMENTED LOCAL；workspace scoped CSS | PASS local：真实App短x、长词/CJK、多轮/滚动、截图与尺寸断言 | 非静态示意；不改变回答医疗语义或修BUG-08/09 |
| MT-CHAT-15 / P1 | 多行输入/Shift-Enter、图片/语音/图标发送；busy/disabled/失败重试不丢草稿；U13 | IMPLEMENTED LOCAL；`AssistantScreen.tsx`、`Icon.tsx` | PASS local scoped：44相关组件测试、实际App多行/照片预览，原BUG01中英发送历史浏览器回归 | ASR/TTS原生设备/在线图像识别NOT RUN；复用原send/idempotency |
| MT-CHAT-16 / P2 | Header品牌+独立panel toggle，Sidebar顶部文字新对话；返回与关闭含义分离；U13 | IMPLEMENTED LOCAL；`ConversationSurface.tsx`、`ConversationHistoryBrowser.tsx` | PASS local：新建真实A/B，panel aria-expanded/control，顶部仅sidebar收起时保留可访问新建；mobile简称AI助手 | 日期仅视觉分组，稳定ID不变；无新API |
| MT-CHAT-17 / P1 | Today 内嵌助手的恢复对话和当前回合统一折叠；每次离开/返回 Today 后保持收起；U14 | IMPLEMENTED LOCAL；`AssistantScreen.tsx` | PASS local：`AssistantWorkspace.test.tsx`；真实 App 浏览器用例验证发消息后离开再返回时完整聊天折叠 | 尚未部署；非 Today 完整 Workspace 不折叠聊天时间线 |
| MT-CHAT-18 / P2 | “查看今日用药”从 Assistant 快捷入口跳转并定位到真实 Today medication 区域；保留其他 Agent 快捷任务；U14 | IMPLEMENTED LOCAL；`App.tsx`、`AssistantScreen.tsx` | PASS local：真实 App Playwright 用例从内嵌助手及 Workspace 验证目标进入视口 | 尚未部署；依赖客户端滚动行为，不新增 API |

### Agent / Medication Understanding / 患者答案

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-AGENT-01 / P0 | 单Agent有界多步typed tool，确定性policy最终裁决；S01/S02/S05 | IMPLEMENTED；`agent/conversation.py`、`model_tools.py` | PARTIAL：模型/工具结构测试，旧Gemini证据限特定场景 | 有多步基础≠每个问题正确调用和回答 |
| MT-AGENT-02 / P1 | 未给药名先查当前药，唯一解释、多种列真实名字选择；U05/BUG-02 | IMPLEMENTED；`agent/current_medication.py`、`conversation.py` | PARTIAL：`f664c5b`和本地工具序列/choices；旧runtime截图已明确非同版本 | 当前真实provider/runtime未验；list success不是答案通过 |
| MT-AGENT-03 / P1 | 裸药名/序号/规格承接原用途或个人计划任务，重查授权数据；U05→U15/BUG-02 | IMPLEMENTED LOCAL；Conversation+`read_dialogue.py` | PASS scoped：C02三组20/18/20轮、按钮/文字、真实SQL→HTTP、浏览器精确产品 | Gemini/生产未验；过期或无法证明指代时重新选择，不凭旧排序猜测 |
| MT-AGENT-04 / P0 | 药物知识trace不因非法state报23514；U05/BUG-03 | IMPLEMENTED LOCAL；`model_tools.py`、`test_medication_understanding.py` | PARTIAL：删除非法state；按SQL allowlist模拟旧值拒绝/新3tool trace保存 | 非live SQL浏览器重试，owner报错未有最终新版闭环证据 |
| MT-AGENT-05 / P0 | 昨天/指定日期读当时计划和日期，不返回今天；U05/BUG-05；Correctness01 | IMPLEMENTED LOCAL；`temporal.py`、`temporal_doses.py`、typed Agent tools | PASS local：日期/原计划/同日切换/DST/真实PG历史RLS；报告`status/AGENT_CORRECTNESS01_20261018.md` | Gemini/生产 NOT VERIFIED；历史规则只读预览，不补写剂次 |
| MT-AGENT-06 / P0 | 过去自述不得提议今天确认，不借此开补记；U05/S01/BUG-04；Correctness01 | IMPLEMENTED LOCAL；model/fallback calendar guard、occurrence/session recheck | PASS local：过去日期无challenge/event，今天EN/ZH仍需确认；已有确认/幂等回归 | 生产发布安全阻断未解除；不授权DB-01历史写入 |
| MT-AGENT-07 / P0 | 合法错误安全保存trace，不二次CHECK失败；U05/BUG-06；Correctness01 | IMPLEMENTED LOCAL；新028闭集补全，无旧Migration修改 | PASS isolated PG：实际registry拒绝→SQL trace→RLS；非法值拒绝/安全rollback | BLOCKED production028待单独批准，旧生产约束风险仍在 |
| MT-AGENT-08 / P1 | 药物/历史给真实名字/日期/状态，不只数量/导航；U05→U15/BUG-08 | IMPLEMENTED LOCAL；registry/patient renderer | PASS：原4项修复，原30整体30PASS；实际A/B问答及同名规格历史增量 | 当前20项/历史20条明示覆盖边界；不补建历史剂次；生产未验 |
| MT-AGENT-09 / P1 | 跟进本地日期，健康记录不无提示漏项；U05→U15/BUG-08 | IMPLEMENTED LOCAL；滚动observations列表/摘要 | PASS：原遗漏、0/1/5/20条、跨日历周窗口、C02完整问答 | 最近10条/描述摘录均明示；C01时区保护保留；生产未验 |
| MT-AGENT-10 / P1 | 一般用途有来源且易懂，不只答“未确认开药原因”；U05→U15/BUG-09 | IMPLEMENTED LOCAL；ingredient/product scope分离 | PASS scoped：缓存真实标签/79测试；最终2次实时openFDA均matched；初次Metformin失败保留并修解析 | 无真实Gemini；不推盐型/别名/个人处方理由/SG批准；不宣称生产已解决 |
| MT-AGENT-11 / P0 | 引用标签版本/覆盖，US一般信息与个人指示/诊断分开；S01/S15 | IMPLEMENTED；`medication_understanding.py`、`backend/MEDICATION_UNDERSTANDING.md` | PARTIAL：typed openFDA/match/source tests，当前Provider未重测 | 不以修一般用途为借口放宽个人剂量/盐型/释放形式 |
| MT-AGENT-12 / P1 | Gemini不可用明确degraded，不把规则当AI或误归DB错误；U05/S01 | IMPLEMENTED；`conversation.py`、`AssistantScreen.tsx` | PARTIAL：429/503/timeout旧归一化；23514已定位非Gemini | 必须结合HTTP envelope/tooltrace/finalanswer，不只看气泡 |
| MT-AGENT-13 / P1 | 动态药物按钮，点击/文字承接原读取任务；S06 AG-03→U15 **APPROVED** | IMPLEMENTED LOCAL；typed selection/choice、共享按钮 | PASS：真实App→HTTP键盘/重复点击/ZH150/Today共享/不保存；精确产品增量 | 重验患者/会话/10min/候选版本；旧按钮安全失效；不恢复敏感确认 |
| MT-AGENT-14 / P1 | 真实tool结果/来源可展开，不伪造执行；实时进度另分；U01/U05/S06 AG-04 | PARTIAL；`AssistantScreen.tsx`、`registry.py` | PARTIAL：完成trace已有；未证明真实start/finish SSE流 | 可读依据是有效要求；SSE实时进度仅PROPOSED，不强行开发 |
| MT-AGENT-15 / P1 | 同一问题包含服药状态+不明药板等多个意图，分别读记录/安全分流/澄清，不强制每问跑四stage；S02/S21 | 有bounded planner/专用工具，完整复合任务路径EXISTS但未逐项证实 | NOT VERIFIED：旧工作流给明确双问题示例；本轮30项主要为单问题，不能代替复合问句验收 | Correctness02/Multimodal交界补一条真实问题级验收，不新建多Agent架构 |
| MT-AGENT-16 / P2 | 常规已知检查简洁说明，不每次重复长免责声明；异常/新证据才请求核对；S21 | EXISTS；patient renderer/uncertainty UI | PARTIAL：既有短结果/状态保护，但用途截图表现冗长偏题；BUG-08/09已有覆盖归属 | 不以删必要安全边界“优化”；同一缺陷不另开重复任务 |

### 视觉 / 照片授权 / Gallery

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-VISION-01 / P0 | 冻结OpenAPI/真样例/strict adapter/超时重试/embedding相容；S01/S05/S16 | IMPLEMENTED；`infrastructure/`、`docs/external/pharmascan-api-openapi-0.10.0.json` | PARTIAL：0.10 receiver/contract fixture+旧live metadata/照片，非所有POST当前验收 | 外部模型owner独立，不重写/猜响应 |
| MT-VISION-02 / P1 | 照片意图/类型不确定可纠正，OCR与裸药片分流；S02/AG-01/U09 | IMPLEMENTED routing；`application/`、`EvidenceEnrollmentScreen.tsx` | PARTIAL：S16旧provider+S12最新路由，未验证当前全类准确性 | Multimodal & Evidence批次；路由通过≠识别通过 |
| MT-VISION-03 / P0 | 一片双重框不用于计数，高相似≠身份/安全；S01/S02 | IMPLEMENTED GUARD；`domain/policy.py`、vision测试 | PARTIAL：重叠/false-high-similarity负例；模型检测器未证修复 | 外部检测/校准仍未验；守卫不应删除 |
| MT-VISION-04 / P0 | 个人reference须owned/当前plan/模型space资格，包装不进裸药空间；S01/S05 | IMPLEMENTED；`personal_gallery.py`、`domain/policy.py` | PARTIAL：S08旧livegallery+契约/安全/浏览器证据 | 当前hosted未验；重新embedding需已同意原图和版本设计 |
| MT-VISION-05 / P0 | Catalogue仅candidate；不清/unknown/未登记可重拍或弃权；S01/S02 | IMPLEMENTED scoped；`personal_gallery.py`、`VisualCheckScreen.tsx` | PARTIAL：候选/uncertainty测试；真实产品覆盖和阈值校准不足 | 不宣称独立药物鉴定、广泛SG覆盖 |
| MT-VISION-06 / P0 | 标签字段仅据明确原文，缺失/模糊保留，禁规格推剂量；S01/S16 | IMPLEMENTED boundary；`source_preview.py`、`evidence_enrollment.py` | PARTIAL：旧真实合成OCR漏duration/ER已记录，receiver有不等于模型识别正确 | 多语言条件指示/ER/处方需外部owner及集成验收 |
| MT-VISION-07 / P1 | 阈值/unknown/ambiguity用独立held-out校准与model/space版本证据，不能任意cosine阈值或0.99=99%；S01/S03 V003/S21 | 模型metadata/契约存在，真实校准报告未独立核证 | NOT VERIFIED：adapter正确接收threshold不证明阈值有效，旧测试/示例非独立数据集性能 | Vision owner/授权评估责任；不改外部权重，不虚构准确率/临床性能 |
| MT-PHOTO-01 / P0 | 分析前明确授权，按owner存许可并可撤销，不默认同意；S01/AG-02 | IMPLEMENTED local；`imageConsent.ts`、privacy UI | PARTIAL：owner/device许可和撤销同步，非跨设备服务端consent证明 | 撤销不等于远端删图/撤回派生历史；隐私语义另审 |
| MT-PHOTO-02 / P0 | 原话/技术证据/历史分离，气泡/标题不带内部JSON；U04/BUG-01 | IMPLEMENTED；`contracts/chat_photo.py`、`AssistantScreen.tsx`、`routes/agent.py` | PASS local：`1ea994b`、S06 boundary/两轮context/ENZH UI，raw证据仅当轮 | 发布和旧污染范围未验；不能全面关闭线上P0 |
| MT-PHOTO-03 / P0 | 照片证据不能授权写入或被当患者明确事实；U04/S01 | IMPLEMENTED；`conversation.py`、`model_tools.py`、`test_chat_photo_boundary.py` | PASS local：只读工具/注入/owner/未来轮无raw evidence负例 | liveGemini误读仍独立验收 |
| MT-PHOTO-04 / P0 | 已存污染范围只读核查，历史处置不得擅改；U04/BUG-01 | NOT ASSESSED production；`DEFERRED_WORK.md` | NOT VERIFIED：确定旧拼接路径，没采生产非正文聚合范围 | 独立批准只读核查；任何清洗/迁移另批 |

### Health / Care / Summary / Forms

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-CARE-01 / P1 | 健康自然空状态/显眼新增，常用可选字段展开、必填可访问；U03/U02 | IMPLEMENTED；健康记录组件、`CareTasksScreen.tsx` | PASS scoped：`abd24c9`/`a510c88`、RecordSemantics及实际UX浏览器 | 不重新实现旧表单；真机另验 |
| MT-CARE-02 / P0 | 健康时间/单位/自述来源/趋势，不推因果或诊断；S01/S08 | IMPLEMENTED；`application/long_term.py`、observations服务 | PARTIAL：旧live合成BP/units/trend，不是临床效果测量 | Agent遗漏另MT-AGENT-09，不用CRUD替代答案验收 |
| MT-CARE-03 / P1 | 跟进显眼新增，可填/取消/确认/更新且留历史；U03/S08 | IMPLEMENTED；`CareTasksScreen.tsx`、`long_term.py` | PASS scoped：旧真实synthetic task、当前Add/required/Cancel表单证据 | 新UI本地，通知送达另验 |
| MT-CARE-04 / P1 | 用药困难/措施/相关跟进保原自述，不推漏服；S01/S08 | IMPLEMENTED；`long_term.py`、相关Records页面 | PARTIAL：旧live barrier/confirmation证据，本轮未重跑 | 不是未实现；发布后抽验 |
| MT-CARE-05 / P1 | 周/月/按计划是真实操作Button，规则报告不冒称AI；U02/S13 | IMPLEMENTED；`ReviewSummaryScreen.tsx`、`review_summary.py` | PASS local：真实按钮/短中长结果及披露/导出浏览器 | deterministic report；统计正确性不能靠UI掩盖 |
| MT-CARE-06 / P1 | 概览/重点/依据渐进；桌面控高、手机自然读，导出完整；U02 | IMPLEMENTED；`ReportDetails.tsx`、`MedicationReviewScreen.tsx` | PASS local：S13长报告/print生命周期/export；未加新LLM | 物理打印/新版native zoom未验 |
| MT-CARE-07 / P1 | 复诊准备事实/未知/问题，可编辑导出，无假医生送达；S02/S08 | IMPLEMENTED；`long_term.py`、`MedicationReviewScreen.tsx` | PARTIAL：旧真实持久化review/download；非医生接收 | Agent日期/覆盖问题不能被漂亮结果掩盖 |
| MT-CARE-08 / P2 | 新LLM每日/周月总结、缓存/历史；S06 UX-01/U02；**PROPOSED** | NOT IMPLEMENTED；现有规则报告 | NOT IMPLEMENTED：A1明确不实现此增强 | 后续需真实范围/隐私设计；不是已批立即欠账 |

### Web Push / Voice / 多语言 / UX

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-PUSH-01 / P0 | 确认计划衍生提醒，snooze/取消不写已服，PRN不造固定剂次；S01/S08 | IMPLEMENTED；`application/reminders.py`、reminder UI | PARTIAL：旧schedule/B14/local popup证据 | 提醒显示不等于后台送达 |
| MT-PUSH-02 / P0 | 权限/owned订阅/SW与worker私钥隔离，patient API无私钥；S01/S17 | IMPLEMENTED；`notification_dispatch.py`、`PushNotificationSettings.tsx` | PARTIAL：dated owned订阅/HMAC；available=true/testfalse可以是预期 | 当前设备owner/配置未重核；不把私钥放患者API |
| MT-PUSH-03 / P1 | one-shot链路与真实设备收到/点击分别验；S17/OPS-01 | PARTIAL；`PUSH_OPERATIONS.md` | PARTIAL：一次HTTP200、processed0、future pending1、attempt0 | **没有送达证明**；有due/隔离设备后另批，不自动重复调度 |
| MT-PUSH-04 / P1 | Cron持续调度需scope/去重/停用/监控和批准；OPS-02 | PREPARED；worker/SQL操作文档 | BLOCKED：最后证据Cron0，worker/锁/queue存在非Cron开启 | 当前Cron未重查；设备门槛+新许可，不能自动启用 |
| MT-PUSH-05 / P2 | ICS有限日历导出≠原生闹钟；S04/S19 | IMPLEMENTED scoped；`REMINDERS.md` | PARTIAL：导出/测试存在，日历客户端导入未验 | 原生Android/iOS应用/Alarm非当前必修 |
| MT-VOICE-01 / P0 | ASR手动启动/取消/错误fallback、可编辑、不自动提交/写入；S01/S05/S04 | IMPLEMENTED；`VoiceInput.tsx`、`browserSpeech.ts` | PARTIAL：native事件mock+早期en浏览器证据；披露远端识别可能 | 物理麦克风/设备当前未验 |
| MT-VOICE-02 / P1 | TTS控制/停止、失败留文字，browser默认，云成本另批；S04/S05 | IMPLEMENTED；speech前后端 | PARTIAL：browser测试+旧Tencent TTS单路径 | Tencent ASR旧未注册已被browser默认取代，不再必修云阻断 |
| MT-VOICE-03 / P1 | 中英实际ASR/TTS遵从语言设置；U01/U02/AG-05 | CONFIGURED；`VoiceInput.tsx`、`language.tsx` | NOT VERIFIED：设置speech_locale不证明中文实际识别成功 | 演示语种真机验；模拟事件不算全语种通过 |
| MT-UX-01 / P2 | 暖白/白卡/细边框/共享1120–1200容器及header正文对齐；U02 FINAL | IMPLEMENTED；`tokens.css`、`app.css`、`components.css` | PASS local：S13相同fixture before/after390/1280/1920 | 旧米黄/窄列/equalheight方案已替代，不再重A1 |
| MT-UX-02 / P1 | Today顺序不变/动态0–10药物自然高，不与短跟进等高；U02 | IMPLEMENTED；`App.tsx`、`app.css` | PASS：S13 DOM数量/高度与390/150溢出修复 | 不隐藏真实药，不拿不同fixture假比较 |
| MT-UX-03 / P2 | Me账户+三核心分类+独立应用信息，入口全保留；U02 | IMPLEMENTED；`App.tsx`、`ui/components.css` | PASS：`4ad76f5`/`a510c88`、导航/响应式证据 | 本地；无需重做 |
| MT-UX-04 / P1 | Records总结/四健康入口/用药历史三模块，无假卡片/Carousel；U02/U06 | IMPLEMENTED；`App.tsx`、`HistoryScreen.tsx` | PASS：S13/S10实际App四路由/真实按钮/列表 | 表单/导出保留独立页是允许取舍，不强造master-detail |
| MT-UX-05 / P1 | 390–1920/ENZH/100–150%字体可操作；safearea/输入不挡；U01/U02/U10 | IMPLEMENTED scoped；`app.css`、`ConversationSurface.tsx` | PARTIAL：七CSS宽度+app字体浏览器；旧版有nativezoom报告 | 最新native125/150 zoom、physical键盘/safearea未验；不等同缩CSS宽度 |
| MT-UX-06 / P2 | Detail/form合理maxwidth，返回/label/input基线、必填可选清晰；U02 | IMPLEMENTED scoped；`components.css`及相关表单 | PARTIAL：登记/健康/跟进直接证据，非所有settings/details逐页fresh验收 | 根据共享修改影响定向验，不宣布全站所有表单通过 |

### 发布 / Demo / 交付

| ID / 优先级 | 要求与来源 | 实现/位置 | 验收与证据 | 生产 / 缺口与建议 |
|---|---|---|---|---|
| MT-OPS-01 / P1 | Vercel前端/Render API/独立Dispatcher路由健康及兼容；S17/S19 | EXISTS；`frontend/vercel.json`、`deploy/`、transport | PARTIAL：旧真实health200/401/one-shot | 当前Live SHAs未核验；旧未部署文档/旧200都不是当前全局结论 |
| MT-OPS-02 / P0 | 001–025不重放；026兼容部署顺序，027另批；S01/U10/S09/S12 | IMPLEMENTED scoped；migrations/rollback | PARTIAL：026结果JSON哈希/legacy不变/reconnect；027仅本地SQL | 026有迁移证据，027 NOT RUN；Schema≠app上线；带数据rollback限制保留 |
| MT-OPS-03 / P0 | 同版本生产E2E真实Gemini/Stage2/Auth/DB/设备，不以health/mock代替；S05/U11 | GATED；部署/RC文档 | NOT VERIFIED：分段旧live不等于当前大量未提交代码E2E | 修P0和患者答案后Production E2E，需具体操作许可 |
| MT-OPS-04 / P2 | 自动CI/CD可复现及审批；本轮审查类别，**UNKNOWN原始自动流水线要求** | 本地check scripts存在；未发现`.github/` | NOT VERIFIED：无该目录不足推断所有平台CI不存在 | 缺指定平台/自动流程批准源，不自动记已批缺陷或新建CI |
| MT-DEMO-01 / P0 | 真实WorkBuddy/CodeBuddy使用和≥3截图，不能伪造；S01/S02/S18 | OWNER ATTESTED；私有证据未扫描 | NOT VERIFIED：owner确认存在≠本轮读到/平台已上传 | 只需资格素材/receipt位置，不索取全部开发聊天 |
| MT-DEMO-02 / P1 | 简介/描述/架构/封面/源码链接与能力一致；S02/S03/S18 | PARTIAL；README/architecture/submission文档 | PARTIAL：描述/架构存在；旧品牌/知识工具缺失声明有漂移 | portal当前内容未验；按事实更新一次，不凭旧todo认未做 |
| MT-DEMO-03 / P1 | 真实工具/不确定分支/多日照护演示，视频及正式提交receipt；S02/S03/S18 | UNKNOWN final artefacts | NOT VERIFIED：旧多日local/部分live旅程，不是最终视频/receipt | MS-04补位置或说明当前不需提交；不将缺来源当未提交 |
| MT-DEMO-04 / P0 | 无虚构EHR/Singpass/医生portal/药房订单/临床商业结果；S01/S02 | SCOPED；MASTER_SPEC/SUBMISSION | PASS scoped：规范明确research/外部professional/商业假设 | 真实世界验证不伪造，排除项非欠开发 |
| MT-DEMO-05 / P1 | 独立验证/授权的照护者最小通知；S02 L004/S01 | PARTIAL联系人/consent，delivery未实现 | NOT IMPLEMENTED delivery：S08明确缺，contact CRUD不是送达 | 安全渠道/验证/许可前继续暂缓；非核心演示可延期 |

### 已替代 / 被否决 / 仅建议

| ID | 决策性质 / 来源变化 | 处理 |
|---|---|---|
| MT-OLD-01 | SUPERSEDED：唯一全局Drawer/浮动头像→U01完整主工作区 | 不再为旧Launcher/Drawer修主导航 |
| MT-OLD-02 | SUPERSEDED：Me四卡/Records混排/统一拉等高→U02 FINAL三分类/统一导航/自然高度 | 不同时满足矛盾旧截图，最终暖白覆盖米黄方案 |
| MT-OLD-03 | SUPERSEDED：Records只能逐计划7天/24h、5条本地截取→U06新只读API | 旧dose-history仍有用途；不能说Agent已自动换到新接口 |
| MT-OLD-04 | SUPERSEDED：此前自动本地Commit许可→U03禁自动Commit | 本轮无Git授权，不追补提交 |
| MT-OLD-05 | REJECTED：旧文件清理/untracking/无关ignore→U12明确不准 | 不列为待补授权清理，不删除文件 |
| MT-OLD-06 | SUPERSEDED：S20软abandoned提议→U09物理清理 | 原提议从未获实施许可；旧026编号不可重用，026已用于thread |
| MT-OPT-01 | PROPOSED：固定三栏/全会话搜索/逐消息删除/SSE实时进度；S06 | 不当已批准缺陷；逐消息删涉及审计/衍生摘要另审 |
| MT-OPT-02 | PROPOSED/FUTURE：无字药板新模型/持续训练/原生闹钟/广泛预防/EHR/临床认证；S02/S03 | 不为清台账实施；外部模型owner/许可/临床单独范围 |

## 旧任务ID覆盖

保留所有旧ID，不把旧todo/done直接转为当前需求状态。以下覆盖 `BUILD_PLAN.md` 61项及 `status/tasks.json` 的后补 LT 项；不重新开发仓库创建等一次性历史工作。

| 旧ID | 当前行为映射 |
|---|---|
| D001–D003 | MT-ENG-01/03、MT-DEMO-02；原仓库/规范建立历史 |
| D004–D006 | MT-DEMO-01；真实Tencent资料，助手日志不替代 |
| B001–B003 | MT-ENG-01/02、MT-AUTH-03、MT-SAFE-02 |
| B004–B005 | MT-ENR-01/02/05；regimen version不是疗程 |
| B006–B007 | MT-SAFE-01、MT-AGENT-01、MT-CHAT-01–10 |
| V001–V005 | MT-VISION-01–06；V003真实校准不足，V005 optional |
| A001–A007 | MT-AGENT-01–14、MT-VISION-03–05；A007 optional candidate种子 |
| F001–F006 | MT-ASST、MT-UX、MT-VOICE、MT-REC各行为 |
| OCR01–OCR02 | MT-ENR-03/04、MT-VISION-06；receiver≠提取准确 |
| K001–K002 | MT-AGENT-10/11、MT-SAFE-05；旧K001 todo已不能否认openFDA存在 |
| L001–L004 | MT-CARE、MT-INV、MT-DEMO-05 |
| T001–T005 | MT-SAFE、MT-OPS-03、MT-UX-05；技术测试非功能结果替代 |
| DEP01–DEP03 | MT-ENG-02、MT-OPS-01–03；旧todo不能否认已有线上HTTP证据 |
| S001–S011 | MT-DEMO-01–04；S010社交为optional，不强列必修 |
| R001–R003 | MT-OPT-02；未来研究，不是本次许可 |
| LT-20261016-AUDIT/CARE/LIVE/MANUAL/EDUCATION-PDF | MT-CARE/INV、MT-OPS-03、MT-VOICE、MT-ENR-04、MT-AGENT-10；保留历史快照，不算新完成率 |

## 来源缺失与证据冲突

- **MS-01 / MISSING SOURCE**：MASTER_SPEC引用的144页综合资料及最初竞赛截图/portal硬要求，本轮没有独立核对原件。只在影响scope/提交时补关键页或原件位置，不要求重发全部聊天。
- **MS-02 / MISSING SOURCE**：不在可见对话、仓库Prompt/decision/report中的补充不可访问；不得推测重建。现有Prompt文件只覆盖已存会话，不等于完整个人追加历史。
- **MS-03 / 历史来源仍缺、当前行为已明确**：需求审查当时无法证明旧版“默认/选择后保持展开”批准源，code当时默认false/选择关闭。随后U13明确批准C.1并完成本地行为验收；无需再请owner为当前开发补旧截图，不能反称旧C当时已经满足。
- **MS-04 / MISSING SOURCE**：最新视频/封面/PPT/提交receipt位置，Tencent私人原图本轮未扫描。缺原件≠没有素材或未提交。
- **局部读取限制**：`outputs`下5个launcher/reload临时目录拒绝访问；非已知需求主源，未绕权。`WORK_LOG.md`含混合编码，部分区段只能容错定位，未转码覆盖；结论优先使用独立UTF8报告/代码/测试。依赖包、缓存、PG数据和私人Tencent目录未递归扫描。
- **EVIDENCE CONFLICT：**S06 BUG-01顶部仍说未提交，后文/Git证`1ea994b`已本地提交；这里只纠正状态，不据此证明部署。AG-06旧只读边界被新thread覆盖，但legacy仍只读。
- **EVIDENCE CONFLICT：**一般回归数百通过与本轮20个患者语义失败并存；覆盖不同，不能宣布Agent正确。旧21失败减少为20只支持长中文预算一项已改善。
- **EVIDENCE CONFLICT：**S12“完成本地修改”不能覆盖audit-linked草稿删除/附件持久恢复/现行计划编辑旅程未完成。源报告已有partial说明，不将其改写为全PASS。
- **EVIDENCE CONFLICT：**同名浏览需求已实现，不等于可信ingredient归组；U08已改变患者筛选目标，不能继续阻断或擅自做Schema映射。
- **EVIDENCE CONFLICT：**示意板明确标“不是真实运行结果”，不作控件验收；后续真实App证据可证明特定本地路径，不能推生产Supabase新查询通过。
- **版本差异：**S19准备阶段“no deployment performed”不代表当前全未部署；S17真实one-shot processed0不代表推送送达或Cron启用。旧Stage2 0.8契约由0.10接收器替代，旧材料不重跑或删除。

后续只能依据新代码/测试/明确决定更新现有ID；保留历史、风险、审批门槛及证据环境，不把资料缺失解释为未实现。


## Final Integration evidence update (2026-10-18)

Earlier rows are historical snapshots where they say no real Gemini/no physical draft-delete evidence. Current acceptance and production boundaries are in `status/RELEASE_READINESS_20261018.md` and `outputs/REAL_GEMINI_RELEASE_QA.md`. IDs and sources are retained.

| Existing requirement | Current additional direct evidence | Remaining gate |
|---|---|---|
| MT-ENR-11 / DB-06 | PASS isolated PostgreSQL + HTTP/service/RPC/refetch404, protected history refuses atomically as currently requested | Production027 approval and deployment; no audit-history deletion |
| MT-AGENT-03/08/09/10/11 | Actual Gemini45 wire requests plus live openFDA, continuous24turns and targeted failures/fixes; complete actual replies retained | PARTIAL real-provider scope; no95% or clinical claim, no hosted joint test |
| MT-AGENT-05/06/07 | Original30 semantics retained; historical write pre-model refusal; actual SQL safety | Production028 and safe backend rollout pending |
| MT-VOICE | Abort/retry/navigation/timeout/expiry/no-auto-send automated evidence | Android physical microphone NOT VERIFIED |
| Records fallback block | User explicitly rejected redundant current-medicine section; removed; actual query now handles pre027 projection | Existing fallback acceptance SUPERSEDED; hosted path pending |
| Summary/Review | Record overview/highlights/questions/details + full numeric measurements; actual browser evidence | Hosted pipeline and external release verification pending |
| Repository maintenance | Guide, full catalog, manual metadata + generator, actual hash-based cleanup | Publish only reviewed public source; internal/history not automatically staged |
| Final Integration / DB-07 | New029 narrows actual observed default ACLs;45related SQL cases and real Gemini/newSchema join verified locally | Production027/028/029 approval pending; no production safety claim |


### 2026-10-19 targeted release supplement

| Requirement | Actual evidence / state | Boundary |
|---|---|---|
| Production027/028/029 | COMPLETED: scoped runner, matching live ledger, RPC/RLS/audit/ACL verification; prior private backup restored69tables | Not a frontend/backend deployment or successful production draft-delete test |
| Gemini retry/patient routing | COMPLETED scoped: bounded SDK retry and 24-turn final continuous EN/ZH actual patient replies; initial failure retained |16new real API requests,61cumulative; no universal accuracy/availability claim |
| Source scope/localization | COMPLETED scoped: optional source-label name, known-form product-family preference, ingredient boundary, Chinese units/route/options | Naturalness PARTIALLY COMPLETED; sources do not confirm patient products or prescribing reason |
| OCR safe review display | COMPLETED scoped: original candidate ER/20:00/course words are visible and unconfirmed; editable existing time fields | Stage2 extraction enhancement is not implemented by this client change |
| Git publication | Owner approved selective local commits only; unrelated successor-plan/detail-page work remains independent | No Push/Deploy authorization |


### 2026-10-19 Medication Gallery attachment supplement

| Behavior / source | Status and direct verification | Boundary / next action |
|---|---|---|
| Global gallery search, filters, deterministic sort and incremental rendering; attachment §§3, 11, 13 | **PARTIAL — local UI**. Component covers product-name/brand search and separate same-name medication IDs; synthetic Chrome confirms search against the mocked patient gallery. | Data still loads as one unbounded patient-scoped gallery response. UI pagination limits rendered cards only; server paging and ingredient-level product grouping need an existing public API contract. |
| Product-specific gallery identity, direct URL and refresh; attachment §§2–4, 13 | **PARTIAL — mocked browser scope**: medication-ID scoping, `#gallery?medication_id=...` refresh, and the Medication Detail callback pass. | Browser Back from Medication Detail restored the gallery hash but the synthetic page body remained blank after 500 ms; route restoration is unresolved. Hosted deep links and callbacks against persisted authenticated records were not exercised. |
| Add-photo workflow: device/file entry, content, provenance, association, consent and comparison opt-in; attachment §§6, 9 | **PASS — local simulated scope**. Component tests 19/19 and synthetic Chrome journey 2/2; `source` evidence is covered by backend suite 26/26. The API keeps comparison false by default and only accepts it for the existing reviewed loose-pill pathway. | Device camera permission, physical devices and hosted API/Storage were not exercised. Structured provenance is still encoded in the existing free-text source field. |
| Upload limits and eligibility; attachment §§2, 4–5, 10 | **PARTIAL — code audit**: request MIME/signature and 8,000,000-byte cap, 16,000,000-pixel image normalizer cap, 10 MiB private bucket object cap, and at most 50 compatible references per comparison run were found. Source/package/blister do not enter the loose-pill embedding path. | No per-product image count or total patient-storage quota was found. Supabase policies and limits were inspected locally but not re-proved against the hosted service in this task. |
| Photo detail and lifecycle management; attachment §§7–8, 13 | **PARTIAL — local simulated scope**. Full private image preview, metadata display, and a separate confirmed stop-comparison action are covered; backend retirement preserves the image record. | Current public contract has no photo metadata correction or ordinary evidence deletion operation. Do not infer either capability; owner-scoped API/audit contract is deferred as `MED-GALLERY-01`. |
| Regression/build/browser checks | **PASS local**: targeted Vitest 19 passed; backend medication evidence 26 passed; synthetic authenticated Playwright 2 passed; TypeScript, ESLint, Vite build and scoped Ruff passed. | Browser fixtures are mocked and synthetic. Real Auth/RLS/Storage, external provider and device-camera behavior remain NOT VERIFIED. |


### 2026-10-19 Patient Answer Quality supplement

- **APPROVED / PASS local scoped:** concise complete EN/ZH lists; shared sourced ingredient explanations without identity merging; readable reviewed plan dose/time; default-collapsed source brand/version/link/original text; exact relevant medication options; conservative unique stronger-product resolution; click/text continuation; new-intent interruption; stable trusted IDs across language changes; explicit faithful original-instruction requests.
- Implementation: existing MedicationUnderstandingService, ReadDialogue/Registry and AnswerSources. New optional clarification flag defaults false; no database schema, retrieval-provider or sensitive-write contract change.
- Acceptance/evidence: twelve-row matrix and actual before/after outputs in `outputs/REAL_GEMINI_RELEASE_QA.md` (`Patient Experience Refinement`); 227 backend /2 source unit /4 actual local browser checks. New Gemini, PostgreSQL, hosted deployment and physical-device runs are **NOT RUN** for this presentation refinement.


### 2026-10-19 Final Provider acceptance supplement

- **PASS scoped after repair:** actual Gemini multi-tool results preserve all sourced medicines; subsequent source queries retain trusted references; deterministic5/10mg clarification, structured continuation, stronger-product resolution and yesterday interruption verified in the same configured Agent. Initial two FAILED replies remain in the actual transcript.
- Model gemini-3.5-flash-lite;15new HTTP requests,76cumulative, live openFDA (including Adapter cache), synthetic local memory patient. No real PostgreSQL/hosted/device rerun. Patient source/product/dose boundaries and confirmation policy unchanged. Evidence: `Final Provider Integration` in outputs/REAL_GEMINI_RELEASE_QA.md.
- **Release scope:** only committed Agent/previous release fixes may be published. Current uncommitted medication-management/gallery/inventory work is not included; successor activation depends on unverified030. Full-workspace readiness must not be inferred from this Agent acceptance.


### 2026-10-19 Medication Gallery real-user QA follow-up

The dated attachment supplement above remains historical evidence for its earlier worktree. This follow-up records the real-use defect review and current local verification; browser and backend fixtures are synthetic and do not establish hosted patient-data behavior.

| Owner issue | Root cause / current behavior | Status and direct evidence | Remaining boundary / approval |
|---|---|---|---|
| 1, 2, 7 — navigation and browser history | Gallery selection previously replaced the active application hash; photo detail was only an ephemeral overlay. Gallery product/all/photo navigation now pushes one history entry, filter/search/sort updates replace the current entry, popstate restores state, and app route initialization preserves the full gallery query. | **PASS — synthetic real-browser history**: Playwright follows Medication Detail → Product Gallery → All Galleries → Back → Product Gallery → Back → Medication Detail; Photo Detail Back/Forward and direct photo URL refresh are included in the targeted gallery/detail journeys. Direct gallery refresh remains covered. | Hosted authenticated deep links and persisted records **NOT VERIFIED**. No new API/schema/permission requirement. |
| 5 — add-reference interaction | The form previously expanded after the grid. It is now a six-step accessible dialog, internally scrollable on desktop and full-screen on mobile, with selected-image preview, step progress, Escape/backdrop/cancel discard confirmation, and retained step state. | **PASS — synthetic component/browser**: save/evidence-only, Escape, safe desktop backdrop, cancellation, and 390/1280 layout paths are covered. | Hosted upload/storage not verified. Existing consent checks remain required. No new API/schema/permission requirement. |
| 4 — dose-check camera | Dose verification previously exposed one file input. It now shares a camera/file acquisition component with gallery entry but sends the selected image only through the dose-check path; it does not enroll it in the gallery. | **PASS — mocked component/browser**: both actions, denied-camera fallback, preview, and stream cleanup are exercised. | Physical mobile/desktop camera permission, device capture quality, and real-device stream behavior **NOT VERIFIED**. No new API/schema/permission requirement. |
| 6 — product/regimen readability | Repeated same-name records were hard to distinguish and regimen dates/status were not prominent. Cards now keep medication IDs separate, show compact current/historical states, product strength/form, plan version and actual course dates when present; missing dates are stated as missing. | **PARTIAL — local synthetic UI**: search/filter/sort and separate same-name product identities remain functional; browser and component regression tests pass. | Actual patient historical data coverage and hosted rendering are **NOT VERIFIED**. Missing server paging and structured product grouping remain under `MED-GALLERY-01`; no raw UUIDs are shown. |
| 3 — localization | One add-photo button used a different English key from the translated modal title; gallery labels and source values now use the existing EN/ZH translation path. | **PASS — synthetic EN/ZH browser checks**: search/status/add/camera/file/form labels, metadata source and validation copy are localized in affected flows. | Full language coverage outside the touched gallery/camera flows is not claimed. No API/schema/permission change. |
| 8 — unknown content/classification | The gallery did not previously run a classifier merely because “unknown” was selected. Stage2 `/v1/check-input` already exists for source routing; the UI now offers it only as a one-time, explicitly consented, source-labelled suggestion. The user's selection remains editable and does not determine eligibility. | **PARTIAL — code audit + DEMO_ONLY synthetic backend fixtures**: abstained/unknown content stays associated evidence; no generic classifier or packaging-recognition claim was added. | Live Stage2 response behavior/version and category accuracy **NOT VERIFIED**. A new model/API is not introduced. |
| 9 — consent and association | The existing API requires `X-Stage2-Consent` for private photo storage/processing; the UI keeps explicit association confirmation and storage consent, and separates optional comparison consent. Copy states association is not exact-product identity. | **PASS — local component/API contract**: submit controls are gated; evidence-only storage remains possible and comparison stays opt-in. | Legal policy review and hosted storage behavior are **NOT VERIFIED**. No consent contract was removed or prechecked. |
| 10 — image type, eligibility, and duplicates | Upload previously trusted the chosen category before embedding. Comparison uploads now call the existing Stage2 route and require checked, non-abstained `loose_pills` classification before embedding; mismatch, unavailable classifier, or unavailable embedding stores evidence only. Check queries admit only rows with the classifier-backed reason. SHA-256 normalized-content identity makes repeats idempotent per medication; legacy eligible rows lacking this provenance are projected out of active comparison without deletion. | **PARTIAL — synthetic backend evidence**: 35 focused backend tests cover package/label/unknown selected as loose pill, unsupported MIME/signature, unavailable classifier, sequential/concurrent duplicates, cross-patient and same-name distinct medication identity, and evidence-only outcomes. | No actual Stage2 call, isolated SQL/Storage, production image access, or patient data was used. Existing backend routes/contracts suffice for this slice; no migration/RLS change. Persisted classifier/version/override provenance for future correction requires the bounded owner-reviewed API/schema proposal recorded in `MED-GALLERY-01`. |
| Regression/build | — | **PASS — local**: full Vitest 268 passed across 51 files; after route/modal-handler corrections, affected frontend tests passed 40/40; five targeted Chromium Playwright journeys passed, including real Back/Forward, photo refresh, upload save/cancel, and EN/ZH responsive layout; backend focus passed 35/35; TypeScript, ESLint, Vite build and scoped Ruff/format/diff checks passed. | Component/mocked browser evidence only; private database/storage, hosted service, and physical device acceptance remain separate. No production migration, RLS/storage change, deployment, or real patient write was run. |

- Issue 10 boundary detail: evidence-only uploads made without comparison consent may retain the user's selected type as metadata even when that description is wrong. This is a metadata accuracy limitation, not comparison eligibility: the selected type alone cannot create an embedding or active reference, and matching queries require the classifier-backed server eligibility reason.

### 2026-10-19 Gallery route-restoration regression supplement

- **Evidence conflict retained:** the owner reported Medication Gallery → Medication Detail → browser Back restoring the gallery hash with a blank body. The exact synthetic Chromium journey did not reproduce a blank body in the current worktree before this correction; it restored the product gallery. The earlier failure is not erased or treated as disproven for other environments.
- **Local correction:** `PersonalGalleryScreen` now gives a medication ID in the restored gallery URL precedence over a potentially stale `initialMedicationId` prop. The prop remains the hand-off when Medication Detail opens `#gallery` before a product query exists. While scoped gallery data is loading, the screen presents its loading status and does not present an empty-gallery state.
- **Direct evidence:** `MedicationEvidence.test.tsx` and `navigation.test.tsx`: 36/36 passed, including stale-prop versus URL identity and delayed scoped data. Targeted Chromium gallery/detail journeys: 5/5 passed; they exercise global gallery → product → browser Back/Forward, product gallery → Medication Detail → browser Back, app Back, All Galleries, and direct product URL refresh. `npm run typecheck`, `npm run lint`, and `npm run build` passed (existing Vite large-chunk warning remains).
- **Status:** PASS for the covered local synthetic route journeys; the owner's exact blank-body observation was **NOT REPRODUCED** in this environment and hosted authenticated routes/persisted records remain **NOT VERIFIED**. No API, schema, permission, or deferred `MED-GALLERY-01` work was added. No production data, migration, deployment, staging, or commit was performed.

### 2026-10-19 Gallery camera, classification-boundary and duplicate-feedback correction

- **Supersedes the earlier classifier claim above for the current implementation.** `/v1/check-input` is workflow routing, not validated general image-content classification. `/v1/detect` and `/v1/scan` detect pill candidates, `/v1/embed` creates pill-space embeddings, `/v1/identify` returns candidates, and `/v1/read-label` performs OCR. None independently proves that the whole image is a loose pill or that it is the associated product. No general packaging/label classifier or calibrated content-confidence contract was found.
- Gallery uploads no longer call `check-input` or Stage2 for category suggestions. User-selected image kind remains descriptive metadata. The application stores uploads as associated evidence and does not generate embeddings or activate comparison. The matching query excludes historical eligibility rows without a currently supported provenance reason; metadata is projected as associated for gallery reads, while persisted photos, embeddings and audit records remain untouched. No production patient records were inspected, so whether any specific previously misclassified image entered the historical active set is **NOT VERIFIED**. The earlier code path could create an eligible reference when a user selected loose pill and the Stage2 route returned checked/non-abstained `loose_pills`; this establishes an eligibility-boundary defect in code, not the contents of historical records.
- Exact duplicate detection uses SHA-256 over normalized image bytes with medication-scoped deterministic IDs. Memory writes are lock-protected; persistent inserts use the existing unique `(patient_id,id)` key with PostgREST `ON CONFLICT DO NOTHING` and return the inserted/existing status. The response now includes `{photo, duplicate}` so the UI can explain a duplicate without claiming a new save. Duplicate identity is scoped to patient and medication, not globally. Concurrent Storage PUTs use the same patient/medication/content-addressed path; real Storage race behavior is **NOT VERIFIED**.
- Camera capture calls `getUserMedia` from the user's button gesture only in a secure context, distinguishes permission denial, missing device, busy/unreadable device, unsupported browser, insecure context and other errors, and offers an explicit file-selection fallback. Preview capture runs through the same PNG/JPEG and 8 MB validation before returning the file to its caller; it does not save automatically. Unit and mocked browser evidence does not verify Windows hardware, real browser permission state, physical capture, or stream behavior on a device.
- Gallery and dose-check camera controls reuse `PhotoAcquisition`; camera images remain in the caller's existing flow and are not automatically enrolled in the gallery. Chinese translations were added for the missing Medication details label, gallery detail/upload strings, duplicate feedback and camera errors. Photo Detail still supports the existing stop-comparison action where the server reports an eligible record; it does not expose deletion. The existing API only retires comparison eligibility while preserving evidence. Ordinary evidence deletion and association removal have no safe gallery write contract and remain deferred.
- **Verification scope:** focused synthetic backend evidence/upload tests and mocked frontend component/browser journeys pass as reported in the 2026-10-19 task record. No Stage2 provider request, isolated real database/Storage test, production image read/write, camera hardware test or deletion test was run. The additive upload response DTO changes the existing API response shape but requires no migration; update any external API consumers before deployment. Direct access to the existing authenticated `store_personal_reference` RPC remains a database write surface whose SQL/privilege hardening needs independent owner approval; the current gallery application write and match-query paths fail closed.

- Final local verification for this correction: backend evidence and upload validation `38 passed`; targeted Vitest camera, gallery and dose-check components `31 passed`; synthetic Chromium gallery/upload/duplicate/localization flows `5 passed`; TypeScript, ESLint, production build, scoped Ruff and Ruff format checks all passed. Vite reports the existing >500 kB chunk advisory. The browser used synthetic API responses and a mocked denied-camera error. No actual camera device, Stage2 call, isolated Supabase database/Storage run, production record query, or deletion flow was verified.

| Acceptance item | Status | Evidence and remaining boundary |
|---|---|---|
| 1. Gallery/dose-check localization | **PASS — local mocked browser** | EN remains the resource key; missing Chinese gallery, camera, validation, duplicate, accessibility and routing strings now use existing i18n resources. Browser verifies the Chinese Medication details label and camera-denial message. |
| 2. Camera permission and capture | **PASS — mocked browser/component** | Secure-context gate, direct user-gesture `getUserMedia`, distinct permission/device/busy/unsupported/unexpected errors, preview, capture, validation reuse, cancellation and track cleanup are covered. Windows/Chrome physical devices and real permission prompts remain **NOT VERIFIED**. |
| 3. Classification and active-reference safety | **PASS — application boundary; historical data NOT VERIFIED** | The gallery no longer uses check-input routing as classification. User category stays explicitly described metadata; uploads remain evidence-only with no embedding; matching excludes legacy rows without approved provenance. The authenticated storage RPC remains separately callable and needs approval-gated SQL/RLS hardening. No production image rows were read, corrected or deleted. |
| 4. Duplicate upload feedback | **PASS — synthetic service/component/browser** | Repeated normalized bytes return `duplicate=true`, preserve the existing photo metadata, keep the form available, link to the saved photo, and allow replacement. Concurrent memory writes and PostgREST conflict parameters are tested. Real Supabase concurrent Storage behavior remains **NOT VERIFIED**. |
| 5. Photo management/deletion | **PARTIAL — deletion deferred** | Existing stop-comparison preserves evidence. No association-removal or ordinary evidence-deletion API exists; no decorative Delete action was added. The smallest safe API/audit/Storage proposal and owner-approval gate are recorded under `MED-GALLERY-01` in `DEFERRED_WORK.md`. |

## Migration 030 pre-deployment assessment (2026-10-19)

| Requirement | Status | Direct evidence and environment | Remaining action |
|---|---|---|---|
| Verify production migration ledger for 027–030 | **PASS — pre- and post-apply production metadata read-only** | Immediate pre-apply check showed 027/028/029 applied with matching hashes and 030 pending at the reviewed hash. Post-apply check shows all four ledger hashes match local files and the activation RPC exists. Both checks were transaction-read-only and read no patient rows. | None for the migration ledger. Hosted backend deployment remains separate. |
| Validate successor activation, ownership, audit and rollback | **PASS — isolated PostgreSQL 17.11** | Fresh localhost cluster; 12/12 focused PostgreSQL tests passed, including migration application, authenticated EXECUTE and anon/PUBLIC denial under the isolated database ACL defaults, transaction rollback on late failure, history preservation, predecessor schedule disablement, future unreported occurrence closure, reported occurrence preservation, overlap rejection, cross-patient rejection, rollback and re-application. | Production ACL metadata additionally shows Supabase default `service_role` EXECUTE; production runtime/data-transition behavior remains separate from local SQL evidence. |
| Verify migration/RPC compatibility | **PARTIAL — source, adapter contract and production metadata** | Migration 030 adds the SECURITY DEFINER RPC with pinned search_path and replaces the overlap trigger function. Production ACL metadata shows EXECUTE for `authenticated`, `service_role` and the `postgres` owner; `anon` and `PUBLIC` do not have EXECUTE. Supabase's function default ACL grants service_role, which the migration does not revoke. No table, RLS or Storage policy changes. The current working-tree backend calls the RPC and has adapter tests. | Hosted backend runtime SHA is not verified; a separately approved compatible backend release is required to expose the successor workflow. `service_role` remains a trusted server credential and must not be exposed to clients. Database migration precedes that backend release. |
| Backup and recovery readiness | **PASS — owner-authorized fresh archive and isolated restore** | Fresh read-only PostgreSQL 17.11 backup created for project fingerprint `029920a09d0f`; archive readable (1,214,863 bytes), roles exported without passwords, and private restore verification matched all 70 tables. The new report is preserved separately at `outputs/release/backup-verification-pre030-20261019.json`; the prior canonical report was restored byte-for-byte. | Archive covers database content, not Supabase Storage object bytes, platform secrets, network/Cron state or PITR. A separate Storage recovery plan is still needed for those assets. Rollback restores the prior overlap guard and drops the RPC but does not reverse activation data after use. |
| Production execution | **PASS — owner-approved scoped migration applied** | The owner explicitly approved migration 030 after the preflight checkpoint. Immediate read-only recheck confirmed the reviewed hash and pending state. `python scripts/db.py migrate --only 202610190030` applied only 030. Post-apply read-only verification confirms matching ledger hash, RPC presence/signature, SECURITY DEFINER, fixed search_path, effective grants, overlap trigger, 35 public tables with RLS enabled (34 FORCE RLS), 37 public policies and 367 public columns. No patient rows or production write smoke tests were used. | No app deployment was performed. Hosted backend runtime SHA remains unverified; application deployment and authenticated hosted acceptance need separate approval. Production audit/data-transition behavior is supported by isolated PostgreSQL tests, not a destructive production test. |


## MED-LIBRARY-01: Medication-centred file library (2026-10-19)

Owner request: consolidate the existing global medication gallery and product-specific reference-photo page into a medication-centred photo/source library. This supplement is additive; earlier MED-GALLERY evidence is retained.

| Acceptance behavior | Status | Evidence and boundary |
|---|---|---|
| Overview shortcut and global/product page names | **PASS ? local component and browser** | Overview shortcut now says Medication Library / ????? with the requested Chinese description. Global and product page titles are My Medication Library / ??????? and Medication Files / ????. All Files is a distinct product-page history entry. Existing app/back and photo routes remain in place. |
| Medication grouping, regimen distinctions, search/filter/sort | **PASS ? synthetic component/browser; PARTIAL for duplicate medication IDs sharing one product_id** | The global endpoint still returns one card per patient-medication ID and nests all of that record?s regimen versions, so regimen versions do not create duplicate cards. Separate medication IDs, including same-name entries with different strengths, remain distinct. Search covers name and the available product evidence fields. Filters cover image/source-document availability and regimen state; sorting uses name, actual source/image/regimen/task update timestamps and available counts. Separate medication IDs are not collapsed solely because a product ID might match. |
| Source document relationships | **PASS ? synthetic service tests** | Read aggregation uses only owner-scoped source IDs from patient medication, medication_source_links, regimen_versions, evidence-image source_id, and evidence-task source_ids; source fields are fetched after verifying the source is owned by the same patient. A synthetic test verifies the original enrollment image and extracted source record, and a source record linked to a regimen version. No name-only association is used. |
| Unified photo/source-image grid and exact file grouping | **PASS ? synthetic service/component/browser** | Reference and evidence images, including original enrollment source images, are returned through one per-medication files view. Records sharing the exact private storage path are grouped into one file card with combined purposes and retained image IDs. Similar names or content do not deduplicate. The existing authenticated private-image endpoint supplies previews. Every card continues to display eligibility separately; this work does not create or enable visual references. |
| Source-document detail/provenance | **PASS ? synthetic component/browser; real persistence NOT VERIFIED** | Source detail uses the actual linked source DTO, its stored extraction evidence, patient-reviewed source fields, source review status, recorded link/image time, medication identity, linked regimen version IDs and existing private source-image IDs. OCR/extraction is labelled as an unverified suggestion, not a verified prescription. The PostgreSQL adapter now reads/writes the already-existing immutable extraction_evidence JSONB column, matching the Supabase adapter; no schema change. |
| PDFs and original document binaries | **NOT IMPLEMENTED ? current contract has no supported PDF file path** | The current source/image upload and private preview routes accept/serve normalized PNG/JPEG images. Source metadata and OCR JSON are not a PDF binary or Storage reference; no PDF card, preview, or count is fabricated. Existing stored source-image records are displayed. PDF ingestion/retrieval needs a separately reviewed owner-scoped binary/storage association and preview contract if desired. |
| Medication Detail/overview scope | **PASS ? source review** | Only the permitted My Medications shortcut name/description changed. Medication Detail was not changed. |

Implementation boundary: added authenticated read-only `GET /api/evidence/gallery/{medication_id}/files` and summary fields to the existing `GET /api/evidence/gallery`; no write DTO, database migration, RLS/Storage permission change, deletion operation, or global bucket query. Image purpose tags mean linked enrollment-source/appearance-reference use; the selected photo description is explicitly identified as user-supplied metadata, not automated classification or proof of visual eligibility.

Direct verification: `tests/backend/test_medication_evidence.py` 37 passed; combined evidence and Supabase adapter tests 61 passed; `MedicationEvidence.test.tsx` 22 passed; `medication-gallery-refactor.spec.ts` 6 Chromium tests passed, including source detail Browser Back/Forward/direct refresh; TypeScript, ESLint and Vite production build passed. Scoped Ruff passed. Browser and component data are synthetic. Authenticated production-like database/Storage retrieval, private Storage scope, real patient records, and PDFs remain NOT VERIFIED / unsupported as stated above.


### MED-LIBRARY-01: final purpose-label and regression verification (2026-10-19)

- Corrected file-purpose semantics: every linked image is labelled as stored evidence; enrollment source is added only when a source-document relationship exists; appearance reference is shown only when the backend reports current comparison eligibility. The files read model applies the same fail-closed legacy-eligibility projection as the gallery summary. This is a read projection only; stored evidence, image metadata, embeddings, and audit rows are not changed.
- Final relevant verification: `tests/backend/test_medication_evidence.py` + `test_supabase_data.py`: 61 passed; affected Vitest files: 32 passed; targeted Chromium gallery journeys: 6 passed; full Vitest suite after the final purpose-label refinement: 278 passed across 51 files. TypeScript typecheck, ESLint, and Vite production build passed after the UI refinement; scoped Ruff check/format passed. Existing warnings: pytest cache permission warning and Vite bundle-size advisory. A Ruff format check initially requested one formatting-only adjustment; it was applied and rechecked.
- Environment boundary: all browser and backend tests use synthetic fixtures/mocked authenticated API behavior. No isolated PostgreSQL document round trip, real patient DB/storage access, or authenticated private Storage preview test ran. PDF bytes remain unsupported and are not represented as file cards. New functionality adds a read-only authenticated `GET /api/evidence/gallery/{medication_id}/files` endpoint over existing contracts; it adds no write contract, schema, RLS, permission, or migration change. Backend/frontend release coordination is required before use outside this local worktree.
### MED-LIBRARY-01 dated supplement - product-file presentation corrections (2026-10-19)

| Requirement | Status | Evidence / scope |
|---|---|---|
| File Purpose `????` and unknown values | **PASS - local component** | The API does not persist a generic purpose field. The service derives `evidence`, `enrollment_source` from explicit source links, and `appearance_reference` from server-reported `eligible` status. The visible corruption was the Chinese translation entry; the UI now translates known purpose IDs and uses `?????` only for an unrecognized ID. No source or comparison purpose is inferred for unknown values. |
| Compact overlapping file filters | **PASS - local component** | Product Files now offers All, Reference photos and Source materials plus date sorting. Reference requires the service-provided eligibility tag; Source follows explicit linked source records. A file with both associations appears in either filter and once in All. Existing comparison eligibility is unchanged. |
| File-card titles | **PASS - local component** | Primary title uses a neutral translated file-type description (Medication photo). Arbitrary `source_description` is retained and shown only in photo details as provenance. No stored data is rewritten. |
| Source records without images | **PARTIAL - local DTO and component** | The section is labelled Other source records. It explains `user_manual` only when the actual source kind says so; other records are described by recorded extraction/field data and the absence of `image_ids`. DTOs cannot distinguish never-uploaded, detached, inaccessible or unsupported original files when no explicit file association exists. No patient-owned production rows were inspected. |
| Source PDF preview | **NOT IMPLEMENTED - contract gap** | `SourceDocumentDTO` and the source-document database row expose source/review/extraction metadata and checksum, but no original-file storage locator or media metadata. Existing image retrieval is patient-scoped and serves `MedicationImage` PNG objects. No PDF endpoint or PDF object association is exposed, so no PDF tile or link is fabricated. Authenticated PostgreSQL/Storage verification remains pending. |
| Verification | **PASS - synthetic local only** | `MedicationEvidence.test.tsx` and `RegimenHistoryScreen.test.tsx` passed 29 tests; `tests/backend/test_medication_evidence.py -k medication_files` passed 2; medication-gallery-refactor browser flow passed 6/6; regimen-history browser flow passed after excluding the expected demo bootstrap/background care-task refresh from the no-regimen-write assertion. No authenticated real Storage/database or physical-device verification was performed. |

Minimum PDF extension proposal: after separate owner approval, add an explicit patient/source-owned file association with private object key, validated media type, display filename, checksum, size and creation metadata; implement an authenticated read-only application service that resolves the file only through the requesting patient and a medication/source relationship, then streams it or returns a short-lived signed URL. Do not list the private bucket from the frontend. If source-document bytes are not already stored, the write/upload contract and its consent, validation, retention and audit behavior need separate review. Any new association schema, RLS/Storage policy change, or production migration requires independent review and approval before execution.

### 2026-10-19 Medication Regimen History navigation continuation

| Behavior | Status | Direct evidence and boundary |
|---|---|---|
| History-only search, lifecycle filters, sorting, same-name regimens, true regimen dates and localized badges | **PASS - synthetic component tests** | `RegimenHistoryScreen.test.tsx` verifies name search, actual `ended`/`superseded` filtering, stable separate regimen IDs, successor-version grouping, date sorting with missing dates last, calendar icons and Chinese labels. `draft`, `pending_clarification` and `active` are excluded from the terminal history list. |
| Navigation from history to the correct regimen detail, browser Back/Forward, app Back, direct history URL and refresh | **PASS - synthetic Chromium** | `npm run test:browser -- e2e/medication-regimen-history.spec.ts`: 1 passed. It reaches history through Medicines, opens a stable-ID regimen record, performs browser Back and Forward, returns with the application Back control while preserving search, then directly loads and refreshes `#past-medicines` at mobile width. No blank-history assertion or page error occurred. Browser requests use synthetic authenticated fixtures; hosted records are not verified. |
| Typecheck and production build | **BLOCKED by unrelated existing workspace errors** | `npm run typecheck` and `npm run build` both stop on TS2379 in unmodified `src/components/CareTaskForm.tsx:41` and TS2322 in unmodified `src/patientDateTime.ts:13`. The changed History component and navigation files produced no reported diagnostics. ESLint passed. These unrelated errors were left untouched. |

The earlier Playwright attempt did not leave a trace or per-test failure report. Its configured `.last-run.json` recorded a pass but did not identify the test. The interrupted assertion is therefore **not reproduced as an application navigation failure**; the focused rerun above passed the complete route journey. No route or component code change was needed. The old process command line was inaccessible, but the existing `127.0.0.1:5174` Vite server was confirmed by HTTP and reused; no duplicate browser server was started.

### 2026-10-19 owner supplement - History shortcut count consistency

| Requirement | Status | Evidence and scope |
|---|---|---|
| Shortcut count matches visible default History cards | **PASS - local synthetic** | The shortcut previously counted every regimen version whose state was terminal or whose end date was before today. The History page instead excludes non-terminal `active` rows and folds versions linked through `supersedes_id`, so a five-version chain could show as one card while the shortcut said five. Both surfaces now use the same pure `historicalRegimenGroups` projection. A component regression test verifies a five-version chain plus an expired-date `active` row produces one shortcut count; the targeted Chromium journey verifies its displayed count equals its two visible cards. No lifecycle state is changed and no API/schema/database work is required. |
| Verification | **PASS - local synthetic** | Targeted Vitest: 16 passed across `RegimenHistoryScreen.test.tsx` and `PatientNavigation.test.tsx`; targeted Chromium: 1 passed; typecheck, ESLint, build and `git diff --check` passed. Browser data is synthetic; no production records were accessed. |

### MED-LIBRARY-01 / MED-GALLERY-01 dated implementation supplement (2026-10-19)

This supplement records local work after the earlier read-only/library presentation evidence above. Earlier test results and deferred decisions remain historical and unchanged.

| Requirement / behavior | Current status | Direct evidence and boundary |
|---|---|---|
| PDF upload, patient-medication association, metadata edit, authenticated preview/open/download and confirmed delete | **PARTIAL — local implementation** | New service and HTTP routes use the verified patient principal, check medication ownership, validate PDF MIME/extension/signature/size, SHA-256 deduplicate within patient + medication, and use the existing private `medication-sources` bucket. PDF content is not sent through enrollment/OCR and does not create a regimen. Unit and UI tests are synthetic; actual Supabase JWT/Storage behavior is NOT VERIFIED. |
| Photo metadata edit, stop comparison, remove from gallery and delete | **PARTIAL — local implementation** | Versioned owner-scoped service/RPC operations audit changes, remove embeddings on ineligibility changes, preserve evidence on gallery removal, and tombstone before retryable private-object cleanup on deletion. Source-linked/shared images are protected. Existing evidence tests and added lifecycle tests run against memory fakes; PostgreSQL trigger/RLS/audit and actual Storage cleanup are NOT VERIFIED. |
| Global medication library counts and PDF files | **PARTIAL — local UI/API** | PDF counts are returned per patient medication, included in document filtering/sorting and shown separately from source-document counts. The product file grid displays PDF records once, with image eligibility remaining image-only. Frontend component tests use synthetic API results. |
| Medication-plan safety and enrollment boundary | **PASS — code-level/synthetic** | PDF upload requires a selected owned medication, stores a patient-supplied file only, and has no medication/regimen write path. Existing enrollment rejects PDF content. No live backend release or database execution occurred. |
| Migration 031, RLS, RPC permissions, audit triggers and rollback | **NOT VERIFIED — local files only** | `supabase/migrations/202610190031_medication_library_file_lifecycle.sql` and guarded rollback are prepared but unapplied. This host has no `psql`, `pg_ctl`, Docker, `pglast` or `sqlglot`, so no isolated PostgreSQL syntax/integration run was possible. Production migration and authenticated Storage checks remain NO-GO pending independent review, isolated DB tests and owner approval. |
| PDF malware scanning and full structural validation | **NOT IMPLEMENTED** | The current server validates extension, MIME, size, `%PDF-` and a terminal `%%EOF` marker. It does not parse the complete PDF structure or scan for malware. Until a reviewed scanner exists, files are served only through authenticated no-store responses with `nosniff`; patient-provided PDFs remain untrusted. |
| Cross-service upload failure recovery | **PARTIAL — known limitation** | Storage upload precedes metadata registration. The deterministic patient/medication/checksum key makes retries idempotent, but an ambiguous DB failure after a successful Storage write can leave an unreferenced private object. Do not clean it automatically without proving no concurrent/committed file row uses the key. A reconciliation/compensation design needs isolated race tests before production release. |
| PDF OCR and prescription understanding | **NOT IMPLEMENTED — future roadmap** | Upload, display and storage do not parse or extract medication instructions. The About page labels prescription-PDF understanding as a future capability; no OCR/model call or plan mutation was added. |

Verification for this supplement: synthetic backend tests `tests/backend/test_medication_evidence.py` and `tests/backend/test_medication_library_files.py` passed 45 tests. Full Vitest passed 289 tests across 53 files; targeted Chromium `medication-gallery-refactor.spec.ts` passed 6/6 journeys; TypeScript typecheck, ESLint and Vite production build passed. Build retained the existing large-chunk advisory. Authenticated PostgreSQL/Storage, browser-backed PDF viewer, and physical-device checks remain separate and NOT VERIFIED.


### 2026-10-19 Today medication follow-up / Care Tasks supplement

Approved source: owner request A–F with seven reference images. Extends MT-CARE-01/03 and Today presentation; it does not reopen Agent historical backfill or authorize production operations.

| Acceptance | Outcome | Direct evidence | Remaining boundary |
|---|---|---|---|
| TC-01/02 | PASS local: visible unreported occurrences; explicitly confirmed taken/not-taken/unsure and append-only corrections, with original plan ownership | New synthetic HTTP tests, actual isolated PostgreSQL RPC/RLS/concurrency tests and real React/local-API browser | Last seven days of existing scheduled occurrences only; no PRN inference, historical occurrence generation, inventory transactions or ingestion proof; production033 not applied |
| TC-03/04/05 | PASS local: modal task creation, field errors/focus, patient-zone dates, historical confirmation/no past reminder, advance/custom reminders, details/edit/reschedule/complete/reopen and readable history | CareFollowUps components, real browser EN/ZH, application tests, isolated SQL queue and legacy dedup/retry tests | Production032 pending separate approval; real device date picker and actual notification delivery NOT VERIFIED |
| TC-06 | PASS local: bounded Today summary, pending before overdue, no completed items, stable task detail deep links | Component ordering test and actual App browser navigation/refresh | Hosted deployment NOT VERIFIED |
| TC-07 | PASS contract/design: read-only source-preserving CareCalendarEvent, stable event ID, date-only course bounds | Contract tests and docs/CARE_CALENDAR_INTEGRATION.md | Calendar UI/aggregation intentionally NOT IMPLEMENTED in this round |

Execution details, changed files, failures corrected and deployment compatibility limits: status/TODAY_CARE_TASKS_20261019.md (local evidence, not hosted acceptance). No stage/commit/push/deploy or production SQL occurred. Existing gallery/library/030/031 changes remain separate.


### 2026-10-19 ? MED-LIBRARY-01 incident/schema readiness continuation

Owner clarification supersedes the earlier hosted-incident assumption: the reported browser origin was `http://localhost:5173`, using local API8001 with the existing production Supabase project. Production catalog reads were explicitly transaction-read-only and inspected no patient rows. See [the complete incident/readiness report](MEDICATION_LIBRARY_RELEASE_READINESS.md) for endpoint dependencies, exact task-owned files, deployment options, unresolved risks and isolated-project setup.

| Acceptance | Current result | Direct evidence / boundary |
|---|---|---|
| Gallery/Alerts/history missing objects | PASS diagnosis; real patient repair NOT VERIFIED |031 `medication_library_files`,033 `effective_dose_events` and `dose_report_entries` are absent from the actual database; local routes/readers referenced them unconditionally. Alerts does not depend on031. Normalized ledger hashes027?030 match;031?033 are pending. No Supabase CLI ledger exists. |
| Compatible030 reads and honest errors | PASS local/mock | Explicit `ENABLE_MEDICATION_LIBRARY_FILES` / `ENABLE_LATE_DOSE_REPORTS` default false; old image/source/event reads remain; missing-object failures use503 PROVIDER_UNAVAILABLE with scrubbed resource diagnostics. Failed gallery reads no longer show empty/registration messages; unavailable031 write controls are gated. Alerts retains polling with15/30/60/120-second failure backoff. |
| Owner-authorized local API-only restart | PASS actual local runtime | Existing documented reload supervisor restarted the API; listener PID changed,5173 remained running. Public `/api/health`200 reports both effective feature flags false. No production configuration or actual `.env` was modified. |
| Actual patient medication/regimen counts | BLOCKED by unavailable browser JWT context | No usable existing patient token or connected browser debugging session was available. Unauthenticated local GETs to `/api/me/medications` and `/api/me/regimens` both returned401; item_count and state distribution remain NOT VERIFIED, not zero. No synthetic result was substituted. `scripts/qa/medication_counts_in_browser.js` is a tested counts-only, existing-browser-session procedure; it never prints credentials or record contents. |
| Previously unidentified unavailable response | PASS identification; feature BLOCKED | Owner supplied Today `/api/me/dose-follow-ups` message `Dose report follow-ups are unavailable`. This is the033 feature deliberately disabled under030 compatibility; do not apply031/033 just to remove its notice. |
|031 UP/RLS/RPC/ACL/audit/concurrency/rollback | PASS real isolated PostgreSQL17.11 |26 tests passed, with fresh001?030 +031 schema and synthetic owners. Initial SQL run13 PASS/3 FAIL exposed JSON-versus-column references, null version bypass and retirement/audit defects; corrected locally. Includes embedding retirement, audit-failure rollback, shared-image association/deletion race and guarded rollback. Supabase platform schemas are local shims, not real Auth/Storage. |
| PDF/photo application and browser behavior | PASS local/mock | Final focused backend230 PASS; five affected Vitest files49 PASS; gallery/history browser9 PASS plus newly added PDF original preview/download/edit/delete browser1 PASS. PDF validation is signature/EOF/size/MIME only, not full parsing or scanning. |
| About PDF understanding roadmap | PASS synthetic EN/ZH browser | Actual About UI identifies PDF understanding/OCR/structured extraction/enrollment as future work and original upload/display as current capability. No OCR/model call added. |
| Authenticated Supabase Storage and file release security | BLOCKED / NO-GO | No authorized isolated project exists. Production bucket is private but size/MIME limits are unset, and owner Storage DELETE/UPDATE policy does not enforce protected-source/tombstone retention. Durable orphan reconciliation, upload/delete races, malware/rate controls and verified Storage recovery remain gaps. No production Storage objects were tested or changed. |
| Final static/build checks | PASS local | TypeScript, ESLint, Vite build, scoped Ruff/format and Git whitespace check passed; existing chunk-size, Starlette and pytest-cache warnings retained. |
| Full frontend regression | FAIL ? shared-worktree integration gaps retained |302 passed,2 failed,1 uncaught error across55 files. `App.test.tsx` lacks new doseFollowUps mock; `RecordSemantics.test.tsx` expects old Care Tasks copy/form. Those files and the other conversation's Today/Care Task implementation were not rewritten here. |

Production031/file-lifecycle release remains **NO-GO**. The local compatibility fix requires no migration; after033 report data exists, disabling its reader/returning to raw events would be unsafe and is not an approved rollback. No production migration/SQL write/schema-cache reload/RLS/Storage mutation/deployment or Git stage/commit/push occurred. Earlier evidence remains historical, with no inferred live acceptance.


### 2026-10-19 Today/Care续接验收补充（保留MT-CARE-03原风险与授权边界）

本地完成默认3条可展开未记录清单、窗口说明、033关闭态不请求/不伪空、032独立能力开关及旧RPC字段丢失保护、Postgres/worker旧Schema兼容、异常旧年份二次核对和原前端回归修复。完整前端308通过，最后时间线保护定向13通过；相关后端95通过及新增保护1通过；真实SQL12通过+新增拒绝3通过（依赖测试加强复验1为重叠）；真实Chrome/React/本地FastAPI五个不同流程通过，模拟Auth/合成内存，非真实通知。原302/2失败/uncaught证据已被本次修复后的结果替代，历史记录保留。

032/033本地契约GO，生产执行/启用NO-GO待独立批准/备份/托管联合验收；031独立NO-GO，不捆绑。027–030未重复，生产未修改。ENABLE_CARE_TASK_FOLLOWUPS、ENABLE_LATE_DOSE_REPORTS、ENABLE_MEDICATION_LIBRARY_FILES默认false且互不启用；已有033报告后不得退回忽略更正的原始事件读取。真实Push及手机原生控件/辅助技术NOT VERIFIED。详见本地status/TODAY_CARE_TASKS_20261019.md续接A–G；后续日历边界见CARE_CALENDAR_INTEGRATION.md。本补充不授权生产、Git或扩大Agent历史写入。

### 2026-10-19 Integrated Release Candidate补充验收

来源：owner本轮Integrated Release Candidate Verification，保留先前Medication Library及Today/Care证据与授权边界。详见[集成发布报告](INTEGRATED_RELEASE_CANDIDATE.md)。Schema030兼容行为PASS本地真实PostgreSQL（Auth与PostgREST传输桥接，非托管Supabase）：真实合成药物/终止疗程/证据图片/未报告剂次、Gallery/Alerts/两种History、旧任务创建与A/B隔离、worker重复同步不重复入队/不提前派送；与兼容unit一起19通过。修复前端按计划结束日期隐藏仍active记录的问题，不更改后端生命周期。完整前端309通过；16个不同Chrome流程通过（17次执行含重跑）；031 SQL26通过；032/033 SQL15通过。完整后端1112通过/1失败/119 opt-in跳过；剩余ScenarioA第17步RESTORE后代词未恢复知识读取，必须保留FAILED，不以组件通过替代。另2个新runner拒绝测试已含上述19通过，未伪称重跑完整后端。

Release A：兼容路径PASS，生产发布NO-GO，尚缺隔离可复现artifact、实际托管SHA和剩余回归处理。Release B031/032/033各自生产NO-GO；真实Auth/Storage BLOCKED、设备及托管患者验收未验证。只读复核027–030已应用且hash匹配，031–033未应用；--only的顺序ledger检查阻止跳过031部署032/033，不能用SQL独立性推断runner支持。没有迁移、生产数据/Storage/RLS变更、Git写操作或部署。

### 2026-10-19 Integrated Release Candidate RESTORE regression follow-up

来源：owner要求修复Scenario A RESTORE后的上下文依赖知识读取。实现边界为Agent内部只读对话解析与对话验收测试；恢复文本仍不是事实或授权。选药引用必须唯一匹配当前工具列出的产品，强度参与解析；如果历史指代仍匹配多个产品，必须继续澄清。直接HTTP/application/tool场景中，明确的Amlodipine10mg问题经RESTORE后以当前药物ID执行来源支持的知识读取；仅有ingredient级Amlodipine历史时仍展示选择，不执行产品级读取。该行为在DEMO_ONLY合成数据、stub planner与缓存公共标签环境下PASS，Scenario A原失败和2个新增聚焦回归通过。相关Agent集合135通过/25 opt-in跳过；完整`pytest tests/backend -q`为1117通过/120 opt-in跳过。未验证真实Gemini、托管Auth/API或生产患者行为。未修改公开DTO/API、迁移、Stage2、feature flag、Storage或Release A兼容逻辑；不要求后端/API兼容变更或数据库迁移。Release A生产仍NO-GO，隔离artifact与托管SHA门保持未完成。

### 2026-10-19 Authenticated Browser Diagnostic修正

来源：owner已登录localhost:5173但旧Console计数脚本误报BLOCKED，并提供Today/Alerts的401与503证据。本地PASS：开发入口复用应用同一SDK的现有会话及HTTP封装，只GET两个固定计数端点；无会话不匿名开户，不解析localStorage，不输出凭据/患者标识/原始记录。Today/Alerts仅观察原有请求的安全阶段与状态，不额外调用会materialize剂次的Alerts。明确拒绝token仍401，身份服务超时/网络/5xx/无效响应改503，仍拒绝访问患者仓库。完整前端317通过、相关后端110通过（其中认证负向30重叠）、实际Chrome/SDK+模拟Auth/API三流程通过、TS/lint/build/Ruff/diff通过，生产bundle不含开发入口。具体用户历史失败原因NOT VERIFIED；不能从BLOCKED或401推断已退出登录或已证明刷新竞争。精确操作、失败阶段与验收矩阵见[AUTHENTICATED_BROWSER_DIAGNOSTIC](AUTHENTICATED_BROWSER_DIAGNOSTIC.md)。没有History/Release A实现、迁移、RLS、生产或Git写操作；其他会话修改保留。


### 2026-10-19 owner-approved Regimen Records supplement

The earlier terminal-history-only display is superseded: default All Courses includes active and terminal confirmed supersedes_id chains; Currently Tracked and Ended filters preserve lifecycle truth. Gallery no longer calls an active elapsed-date plan historical; patient-local warning explains it remains tracked. No lifecycle/database/dose/migration writes. Related local acceptance and commit scope: [REGIMEN_RECORDS_UX](REGIMEN_RECORDS_UX.md). Synthetic component/backend/browser evidence is separate from production verification.


### 2026-10-19 final unified local integration and categorized commits

Owner authorized selective local commits only; existing Regimen Records commit7b2d478 is preserved. Foundation2c1acfe and unified application bf3331a are local snapshots, not production GO. Final acceptance and exact manifests: [LOCAL_INTEGRATION_VERIFICATION](LOCAL_INTEGRATION_VERIFICATION.md). Full backend1129 PASS/128 opt-in SKIP; frontend319 PASS; real isolated PostgreSQL53 distinct cases;23 distinct synthetic Chrome journeys PASS. Old History names/counts, hidden mounted-row locator, missing Files fixture, accessible-name/unsaved-exit expectations and Summary standalone-number expectation are resolved without relaxing consent or lifecycle safety. Migration runner now commits reviewed DDL and ledger atomically, preserving exact hashes and ordered031 -> 032 -> 033 prerequisites; actual rollback-on-ledger-failure/concurrency tests pass.

Real Supabase Auth/PostgREST/Storage remains BLOCKED; PDF parsing/scanning, protected-source Storage retention, orphan reconciliation/restore and cross-service race acceptance remain release gates, with existing IDs/risk/approval requirements unchanged. No production migrations, data/Storage/RLS/config changes, Push or deployment were executed. The previous separate schema030 Release A plan is superseded by owner instruction; compatibility tests are retained as regression coverage, not a separate release. Commit/push authorization never grants production migration or capability enablement.
