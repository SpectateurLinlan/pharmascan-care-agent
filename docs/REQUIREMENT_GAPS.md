# MediThread — Historical Gap Report & Recommended Execution Plan

2026-10-18。范围为 [Requirement Register](REQUIREMENTS.md) 中可追溯来源；不是完整聊天检索、生产巡检、全仓安全认证或本轮开发授权。所有需求 ID 以 Register 为准，本文件不复制一套任务状态。代码与实际功能没有因本轮审查被修改。

## 本轮证据核查

- 只读检查实际分支/HEAD/已暂存/未暂存/未跟踪状态、Git最近提交；读取现有规范、相关Prompt章节、台账、独立完成报告、公开服务/API/Schema/测试定位。
- 复核026生产迁移结果与验证JSON的非敏感字段：migration名、SHA、legacy_rows_unchanged、committed_and_reconnected、test_owners_in_production=0、legacy_contract_columns_present；这是**既存带日期证据**，不是本轮重新连接生产。
- 定向重跑既有 `tests/backend/agent_patient_semantics_audit.py`：30项，**10通过、20失败**。仅DEMO内存fixture；过去日期风险用例不提交确认，未写生产。保留失败，不改实现/预期、不跳过；与旧9/21相比长中文context预算测试通过。
- 本轮命令：`D:/DevTools/anaconda3/envs/pharmascan-care/python.exe -m pytest tests/backend/agent_patient_semantics_audit.py -q --tb=no -p no:cacheprovider --junitxml=outputs/requirements-agent-audit-20261018.xml`，使用既有 ignored 依赖路径。无网络模型、无生产查询/写入、无Dose确认。
- 静态对照：Agent `_get_dose_status`仍使用current regimen，模型Status不能表达昨日；`prepare_self_report`日期防护未满足audit。Records使用独立新只读服务，不会自动修复这些Agent路径。
- Assistant `historyOpen`初始false，选thread后false；现有browser只验展开时并列，没验选择后保持侧栏。附图/需求原始批准来源需要区分，见MS-03，**不擅自补做UI**。
- Enrollment独立库存面板存在，但登记表无初始库存联动；thread附件只有presence，非持久图片引用。027拒绝audit-linked删除是代码明确边界，不是资料不足猜测。
- 没有重新运行整套前后端测试、Typecheck、Lint、Build或浏览器。这是文档/证据任务，历史测试按其环境引用；不拿旧总数冒充本轮结果。只有文档结构/引用/ID/Git检查作为本轮增量检查。

## A. 已提出但未实现

| 需求 / 关联台账 | 真实缺口、原始来源 | 此前未完成原因 / 影响 | 处理建议 |
|---|---|---|---|
| MT-INV-03 / DB-04 | U03后续台账：首次登记初始库存；当前只有独立库存面板 | 联动写入/单位/幂等/部分失败未批准核定；患者需登记后再盘点 | 独立库存小范围方案后批准，不把标签数量导入物理库存 |
| MT-ENR-04 / 旧PDF场景 | S02/S05早期要求PDF，当前患者流程仅图片/手动 | 文档提取应用链路未完成；文件不能直接导入。不是Stage2读取图片即支持PDF | 确认当前release是否仍需；保留有效要求或由owner明确延期，不悄悄取消 |
| MT-DEMO-05 / L004 | 经验证照护者最小通知没有delivery实现 | 联系人/consent不是发送，渠道验证/权限/安全门槛在；影响需要照护者闭环的演示 | 非核心release可延期；绝不假发送 |
| MT-CHAT-09 / AG-06附件子项 | U10要求关联已授权附件，当前仅photo_attached | 复用旧图片链路时选择了presence最小实现；刷新不能恢复原图/引用。报告限制不能抵消需求缺口 | Multimodal & Evidence中给持久引用/授权撤销/保留期限方案，另批敏感存储 |

## B. 部分实现，但遗漏/尚未满足补充行为

| 需求 / 关联台账 | 缺少什么 / 来源 | 原因与影响 | 最小后续范围 |
|---|---|---|---|
| MT-ENR-11 / DB-06 | U09“删除相关记录全部删”只对无受保护引用的纯草稿成立 | immutable audit_events→regimen FK阻断，常见带draft_created审计的路径不能保证可删；内存浏览器成功不证明真实DB常用路径成功 | 单独审计保留/引用方案，实测真实应用create→audit→delete。保留审计、临床、共享证据；不直接cascade/改生产 |
| MT-ENR-13 / DB-06 | 删除图失败有durable receipt但刷新后无待清理入口 | 只做当前页retry，Storage故障后用户重进难发现；数据库行删除≠文件删除 | 与DB-06同一任务下补重入/cleanup查询验收，不创建新重复Task |
| MT-ENR-14/15 | U09同期重复和“到我的药物修改时间/标编辑过” | active overlap守卫已有，pending不唯一；仍需停旧后新版本，没有证明可顺畅编辑现行计划完整旅程；marker本地持久化不等于编辑能力全完成 | 先确认产品允许的计划变更流程，独立写入/版本方案与具体授权；不变医嘱、不改旧source |
| MT-CHAT-11 | U10各药物/记录来源的可靠上下文/返回 | 已有owned ID服务和药物来源旅程；不是每个Records/Medicines入口都验了 | 仅补未覆盖入口验收，不重做工作区/Agent |
| MT-PHOTO-01 / AG-02 | 授权撤销的跨设备、原图/派生历史语义未完整验证 | 设备owner-scoped许可可撤销，但撤销不等于远端清除；用户可能误解保留范围 | Multimodal & Evidence中先文档/真实API范围核定，再批准必要实现 |
| MT-UX-06 | 所有详情页/设置表单受共享样式影响的最终覆盖 | 已验登记/健康/跟进，不是逐页最新真实运行验收；不能宣传全站完全通过 | 变更触及页面时定向补验；无证据不批量重做CSS |

## C. 曾有完成声明，但直接验收不足

| 需求 / COMPLETED CLAIM来源 | 证据不足与真实边界 | 影响 / 下一步 |
|---|---|---|
| MT-AGENT-02/03 / BUG-02本地修复 | 测试证明发现/选药/继续任务；用户旧runtime截图与新代码版本不同，缺新runtime+真实Provider+DB最终答案闭环 | 不把源码存在当当前运行有效。受BUG-09影响，纳入Agent Correctness02真实答案验收 |
| MT-AGENT-04 / BUG-03 | 去掉非法trace state的SQL-derived模拟通过，未有owner新版实际23514重试闭环 | 审计不可绕过；使用真实隔离SQL→API错误/trace验证，再单独hosted验收 |
| MT-CHAT-02/03 / AG-06 | 本地真实SQL保存/恢复通过，但模型是DEMO stateless；不证明Gemini真实指代/事实更新；026不等于应用上线 | 正确报告PASS local、NOT VERIFIED provider/hosted；不用“完整Session恢复” |
| MT-CHAT-06 / sidebar | 只证明侧栏展开时并列，不能证明选中/发送后保持展开；原批准要求是否存在仍MS-03 | code主动关闭，是具体行为；先确认新/旧要求，不反推历史承诺 |
| MT-REC-08/13 | 新PostgREST查询有mock合同和真实local服务/内存，缺真实Supabase新只读路径 | 分页/时间/RLS必须在真实adapter语义验收，不以展示组件PASS覆盖 |
| MT-AUTH-02 | updateUser/OTP代码、模拟SDK不证明真实guest升级保留UID/Storage、已有邮箱冲突 | 账号演示/恢复重要；单独授权合成A/B真实邮箱流程，不自动患者迁移 |
| MT-DEMO-01/02/03 | owner确认有Tencent原证据，稿件/PPT描述存在，官方视频/receipt当前未读 | 不指责未做，不伪造完成；补最终位置/验收凭证足够 |
| MT-AGENT-15 / MT-VISION-07 | 原复合意图示例/独立校准有明确要求；当前单问题audit和metadata契约并未直接验这些行为 | 分别加一条复合患者问题验收与索引真实模型owner校准资料；资料缺失不等于模型没做过校准 |

## D. 测试很多项通过，但患者目标失败

下列缺陷每项只归一次，引用既有BUG，不再创建相同新Task。为何此前“没完成”：普通回归验证了实现约束/局部流程，患者语义audit验证的是问题→真实tool参数→记录/提议→患者最终答案；覆盖目标不同。当前owner已明确要求纠正，不用工程check替代。

| 需求 / BUG | 本轮直接证据 | 影响 / 最适批次 |
|---|---|---|
| MT-AGENT-06 / BUG-04 P0 | `test_past_intake_claim_never_prepares_todays_confirmation` FAILED；未实际确认 | “昨天吃了”可能提今天剂次；写入提议日期安全，Agent Correctness01首项，独立方案/具体授权；不实现backfill |
| MT-AGENT-05 / BUG-05 P0 | yesterday direct/NL/schema/historical-plan用例 FAILED | 回答错日/错计划可能误导下一步；Agent Correctness01只读日期/历史归属修复 |
| MT-AGENT-07 / BUG-06 P0 | 合法错误全集/overlap audit两项FAILED | 重复添加正确被拒却trace存储二次失败，可能再报23514；契约修复，不取消overlap或吞audit |
| MT-AGENT-08 / BUG-08 P1 | 中文四状态、current-list/history中英共8项FAILED | 有tool success却不答实际药名/时间/状态，Patient language属于验收，不是装饰文案；Agent Correctness02 |
| MT-AGENT-09 / BUG-08 P1 | follow-up EN/ZH、health完整性3项FAILED | UTC日期错位/无提示遗漏记录；同BUG下的独立验收行为，Correctness02 |
| MT-AGENT-10 / BUG-09 P1 | 用户Amlodipine截图 + S06诊断；本轮未调用liveopenFDA/Gemini | 普通用途问题被严格产品核验/“未确认开药原因”挡住；一般用途与个人指示证据范围要分开，Correctness02 |

**不能重复开发的已改善行为：**BUG-07长中文context原失败项本轮PASS，当前16KB裁剪保留历史；只需相关边界/真实DB保持验证，不能再照旧提案宣称整个预算机制缺失。

## E. 部署、外部服务或真实设备受限

| 范围 | 已有证据 / 不能推出的结论 | 下一步责任与许可 |
|---|---|---|
| 生产版本/026/027 | 026既存结果显示commit/reconnect、旧数据未变；027仅本地。旧health200不是当前最新应用路径证明 | owner批准发布后operator核Live SHA/迁移目录，数据库→兼容后端→前端；027需单独生产许可和恢复准备 |
| Stage2/OCR/Gallery | 0.10 receiver/旧真实合成照片存在；duration/ER漏识别、未知产品和阈值准确性未闭合 | Vision owner提供真实契约/回归；集成方用允许合成图验证最终安全输出，不能修外部权重或假造“已识别” |
| Gemini/general knowledge | 老单路径成功与本地DEMO续聊不能证明当前真实选药/多步/用途质量 | Correctness02后运行少量真实患者问题级验收；需provider访问/成本和hosted操作许可 |
| Web Push | one-shot HTTP200但processed0/attempt0，未send；最后Cron0 | owner/设备操作者提供隔离订阅+due范围，另批one-shot；receipt/click后再考虑Cron。不可自动重试或启调度 |
| Email/guest升级 | Auth代码和旧模拟证据，不是当前邮箱/永久身份/附件隔离 | owner使用合成账号与可接收邮箱，独立授权Auth/RLS验收，不自动迁移患者 |
| ASR/TTS/keyboard/zoom/print/calendar | 浏览器事件/字体/CSS宽度、旧版本zoom证据不证明当前物理设备中文语音/键盘/打印/ICS导入 | owner/device tester按目标设备逐项记录；不为消除NOT RUN重复跑无关测试 |

## F. 已被替代，不要再修旧版本

- 唯一右Drawer/浮动Launcher、Me四卡、Records混排、强拉动态卡等高、旧米黄/窄容器 → U01/U02 FINAL。
- Records仅逐计划过去7天/未来24小时、静态5条限制 → U06新只读查询；保留旧API用途，不误称Agent也已升级。
- 同名登记作为患者顶层独立项 → U08同名浏览组；可信ingredient映射不再阻断它，原ID/产品记录不合并。
- 原自动Commit许可撤销；旧清理请求被否决；软abandoned方案不是物理删除批准，旧026提议不能抢用已存在thread026。
- 强制Tencent ASR旧阻断被browser默认决定替代；Stage2旧0.8缺字段描述由0.10接收契约更新；不能把旧任务表全部todo当当前欠账。

## G. 仅建议/备选，不应当作缺陷

- 固定三栏、全会话搜索、逐消息删除、structured choices、SSE真实进度、新LLM每日/周月摘要：台账门槛仍在，未获立即实现许可；当前基本聊天/规则报告不能包装成这些增强。
- 权威成分归组残余方案：需授权概念/组合/盐型/来源关系；当前明确同名浏览不要求它。是否继续作为正式产品目标请owner确认，不能擅自删有效原始背景。
- 自动CI平台/全流水线：本轮审查类别不等于owner曾批准某平台方案；未发现`.github`不足推“所有CI不存在”。
- 新模型训练、无字药板、独立原生闹钟、EHR/NEHR、临床认证、广泛疫苗/筛查/独立生活方式引擎、社交发布：未来/排除/optional，不列当前必须开发。

## 推荐后续顺序：以证据缺口，不以旧Phase编号

以下为**建议，不是授权**。现有已通过的A1布局/Records名组/Thread骨架不重建。每轮只选明确矩阵子集，避免一次又报告笼统“所有功能完成”。

| 顺序 / 现有批次名 | 最小范围与退出标准 | 权限 / 风险 |
|---|---|---|
| 1. Agent Correctness01 | BUG-04先提日期提议安全方案；BUG-05读日期/历史plan；BUG-06审计契约。分别验证原话、工具参数、对应发生时间、trace保存和患者答案；past write无确认/错误日期无proposal | P0；写提议/审计/可能SQL必须具体批准，严禁捆绑DB-01历史补记；真实SQL负例，不以mock-only结束 |
| 2. Agent Correctness02 | BUG-08患者可读/完整/本地日期，BUG-09一般用途与个人指示分离；BUG-02/03做最终新版runtime闭环；少量中英真实问题/真实Provider验收 | P1；知识/provider契约先评估，禁止硬编码一般用途/扩展个人医嘱；不自动加DDI |
| 3. Records History & Grouping（验证为主） | 新Supabase只读query/paging/date/RLS定向验收，保留已通过name group/计划ID/confirmed-only；真实范围限制显示 | P1；不重写同名UI，不合并记录、不默认实现ingredient Schema；生产读取依scope批准 |
| 4. Multimodal & Evidence | BUG-01新版发布验证/旧范围独立只读方案；Stage2 label/pill/ER/duration回归；U10附件持久引用及AG-02撤销语义方案 | P0隐私 + P1识别；敏感存储/历史处置另批，真实照片/模型结果和来源/答案验收 |
| 5. AI Summary & Review Preparation | 先核日期/计划/统计口径/遗漏已修，再完善现有deterministic报告可读性；新LLM聚合只有owner明确选择才实施 | P1/P2；不以概览隐藏错误，不自动实现UX-01 |
| 6. Production E2E | 同一版本/迁移/配置，真实Auth、Enrollment/B14、Records、Gemini多步/知识、photo、thread、设备语音/Push；只测已批准目标 | 发布前P0 gate；owner分别批准Git/Deploy/SQL/通知，不能把026已迁移报告成应用上线 |

### 独立遗留项如何安排

- **DB-06删除 / 计划编辑**：用户已批准本地需求，但常见audit-linked草稿仍不可删，不能等待报告自动关单。可与Correctness01审计方案审查协调，**独立**授权/提交范围，不夹带批删生产。027上线前必须解决/接受明确限制。
- **AUTH-01**：Guest绑定真实性是保留患者数据的高风险验收；登录/恢复演示前完成。若不验证，不承诺完整升级成功；不能通过开发新身份迁移“补验收”。
- **DB-04初始库存**：已有库存功能不阻塞基础药物管理发布，但登记一体化诉求有效且未实现；可延期，需明确写入/幂等授权。
- **照片授权/附件**：BUG-01属于优先隐私缺陷，不能因“旧数据需审批”而推迟新发送路径验证；旧历史不擅改。
- **Push**：无设备收到证据就不宣传可靠后台提醒；若以Push为本次发布能力，是发布阻断；若明确排除并披露，基础App可另行演示。Cron需另批。
- **PDF/照护者delivery**：有效早期目标但未闭环；owner明确当前release是否包含，不擅自取消，也不为填六能力声称已支持。

### 现在最多建议推进的3项

1. **BUG-04/05/06 — Agent Correctness01**：已有30项可重现语义audit、现有typed工具/记录模型；缺日期提议方案和真实SQL契约验收。涉及Agent read/write-proposal、audit DTO/可能SQL，高风险。建议现在先批准**独立方案/具体最小实现范围**，不含backfill。
2. **BUG-08/09 — Patient-readable answers/general use**：选药发现/续接基础与openFDA适配已存在；缺可验证的一般用途证据范围、真实provider最终答案。涉及renderer/tool/service契约，中高风险。建议P0 gate后立即做，不再重UI。
3. **DB-06 — audit-linked draft deletion decision**：纯草稿SQL/幂等/owner/确认已有；缺常见审计关联保留设计、真实Storage/重入cleanup和生产恢复准备。涉及审计引用/DDL/API，风险高。建议先决定保留设计，继续暂缓生产物理删除，不顺手清洗。

## 无需再次开发的已存在能力

在已有直接本地/带日期证据范围内：完整Assistant路由/Today原位共享、暖白共享容器、Me三分类、Records三模块/真实筛选分页/同名浏览/confirmed-only、日期天数二选一、成功渐隐、手动退出确认清空、来源设置展开、裸药片入口路由、BUG-01文字证据分离、新thread身份/A-B/本地SQL续聊、库存unknown/ledger/补药、健康/跟进CRUD和规则报告/导出。**不需要重建**，但不能由存在推当前生产可用或所有子项完成。

## 需要owner补的最少资料 / 本轮未完成核查

1. MS-03：若“桌面历史选中/发送后保持展开或默认展开”已经批准，请只给相关原句/截图；否则可作为下一轮明确新增行为。
2. MS-04：若本次还需比赛交付验收，给最终视频/封面/PPT/receipt所在位置或说明已不属当前发布目标；不要求全部Tencent原始对话。
3. MS-01只在原规范/当前scope冲突时补关键页：PDF、照护者delivery、竞赛提交硬项是否仍有效。其他不可见聊天只能登记MISSING SOURCE，不构造历史。

已知来源覆盖15领域，但**无法证明全部个人补充来源完整**。没有获取当前线上SHA、重新读生产Schema/患者数据、运行真实Gemini/Stage2或真机验收；这些是明确NOT RUN/NOT VERIFIED，不是默认功能未实现。
