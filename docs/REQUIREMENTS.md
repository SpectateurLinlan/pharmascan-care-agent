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
| MT-AGENT-03 / P1 | 裸药名承接上句用途任务，读自己的药、跨规格歧义澄清；U05/BUG-02 | IMPLEMENTED LOCAL；`current_medication.py`、`conversation.py` | PARTIAL：EN/ZH choices→Nifedipine LA→Amlodipine上下文测试，S06报告 | 新runtime/真实Gemini+DB最终答案未验，不因单位测试宣称截图问题关闭 |
| MT-AGENT-04 / P0 | 药物知识trace不因非法state报23514；U05/BUG-03 | IMPLEMENTED LOCAL；`model_tools.py`、`test_medication_understanding.py` | PARTIAL：删除非法state；按SQL allowlist模拟旧值拒绝/新3tool trace保存 | 非live SQL浏览器重试，owner报错未有最终新版闭环证据 |
| MT-AGENT-05 / P0 | 昨天/指定日期读当时计划和日期，不返回今天；U05/BUG-05；Correctness01 | IMPLEMENTED LOCAL；`temporal.py`、`temporal_doses.py`、typed Agent tools | PASS local：日期/原计划/同日切换/DST/真实PG历史RLS；报告`status/AGENT_CORRECTNESS01_20261018.md` | Gemini/生产 NOT VERIFIED；历史规则只读预览，不补写剂次 |
| MT-AGENT-06 / P0 | 过去自述不得提议今天确认，不借此开补记；U05/S01/BUG-04；Correctness01 | IMPLEMENTED LOCAL；model/fallback calendar guard、occurrence/session recheck | PASS local：过去日期无challenge/event，今天EN/ZH仍需确认；已有确认/幂等回归 | 生产发布安全阻断未解除；不授权DB-01历史写入 |
| MT-AGENT-07 / P0 | 合法错误安全保存trace，不二次CHECK失败；U05/BUG-06；Correctness01 | IMPLEMENTED LOCAL；新028闭集补全，无旧Migration修改 | PASS isolated PG：实际registry拒绝→SQL trace→RLS；非法值拒绝/安全rollback | BLOCKED production028待单独批准，旧生产约束风险仍在 |
| MT-AGENT-08 / P1 | 药物/历史给真实名字/日期/状态，不只数量/导航；U05/BUG-08 | PARTIAL；Correctness01修复EN/ZH四状态与日期 | PASS local四状态；FAILED current-list EN/ZH和history EN/ZH共4项 | Correctness02保留，不能因工具success关闭 |
| MT-AGENT-09 / P1 | 跟进本地日期，健康记录不无提示漏项；U05/BUG-08 | PARTIAL；Correctness01修复follow-up aware timestamp显示 | PASS local跟进EN/ZH；FAILED observations completeness1项 | Correctness02修复完整性；provider/生产未验 |
| MT-AGENT-10 / P1 | 一般用途有来源且易懂，不只答“未确认开药原因”；U05/BUG-09 | PARTIAL；`application/medication_understanding.py` | **FAILED 用户行为证据**：Amlodipine截图+S06诊断过严product匹配，非本轮live复现 | 真实知识工具存在；需一般用途match scope，不硬编码适应症/假引来源 |
| MT-AGENT-11 / P0 | 引用标签版本/覆盖，US一般信息与个人指示/诊断分开；S01/S15 | IMPLEMENTED；`medication_understanding.py`、`backend/MEDICATION_UNDERSTANDING.md` | PARTIAL：typed openFDA/match/source tests，当前Provider未重测 | 不以修一般用途为借口放宽个人剂量/盐型/释放形式 |
| MT-AGENT-12 / P1 | Gemini不可用明确degraded，不把规则当AI或误归DB错误；U05/S01 | IMPLEMENTED；`conversation.py`、`AssistantScreen.tsx` | PARTIAL：429/503/timeout旧归一化；23514已定位非Gemini | 必须结合HTTP envelope/tooltrace/finalanswer，不只看气泡 |
| MT-AGENT-13 / P2 | 动态可点击真实药物Structured Actions；S06 AG-03；**PROPOSED** | NOT IMPLEMENTED structured UI；现有文本choices | NOT IMPLEMENTED：文本选药不是可点击卡片，但未获即刻实现许可 | 基础答案正确后另批，不作为当前已批准欠账 |
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


### 2026-10-19 targeted release supplement

| Requirement | Actual evidence / state | Boundary |
|---|---|---|
| Production027/028/029 | COMPLETED: scoped runner, matching live ledger, RPC/RLS/audit/ACL verification; prior private backup restored69tables | Not a frontend/backend deployment or successful production draft-delete test |
| Gemini retry/patient routing | COMPLETED scoped: bounded SDK retry and 24-turn final continuous EN/ZH actual patient replies; initial failure retained |16new real API requests,61cumulative; no universal accuracy/availability claim |
| Source scope/localization | COMPLETED scoped: optional source-label name, known-form product-family preference, ingredient boundary, Chinese units/route/options | Naturalness PARTIALLY COMPLETED; sources do not confirm patient products or prescribing reason |
| OCR safe review display | COMPLETED scoped: original candidate ER/20:00/course words are visible and unconfirmed; editable existing time fields | Stage2 extraction enhancement is not implemented by this client change |
| Git publication | Owner approved selective local commits only; unrelated successor-plan/detail-page work remains independent | No Push/Deploy authorization |
