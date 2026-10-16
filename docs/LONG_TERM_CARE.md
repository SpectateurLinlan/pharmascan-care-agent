# Long-term medication care

## Ownership and public interfaces

`LongTermCareService` coordinates inventory, patient-reported barriers, medication-related tasks and review preparation. It depends on `CareRepository`, public enrollment/observation/summary services, dose-event **reads**, dose-rule reads and an injected clock. It has no dose-event write port, provider client or caregiver delivery port. `domain/inventory.py` owns pure ledger/demand rules; React and Gemini do not calculate stock.

Public contracts: `contracts/long_term.py` (`StockInput/StockStatus`, `BarrierInput/Barrier`, `CareTaskInput/TaskUpdate/CareTask`, `CareReview`, `MedicationCareReport`). `SupabaseCareRepository` uses the verified user's JWT. `MemoryCareRepository` is explicitly process-local SIMULATED persistence. Administrative notification work stays outside patient HTTP.

## Data and consistency

Migrations **022** and **023** are additive and applied to the development database on 16 October 2026. They preserve existing records and ledger checksums.022 adds:

- `inventory_transactions`: patient + concrete patient medication identity, unit, count/refill/correction/lost/discarded/damaged, quantity, ledger balance, threshold, note, time and patient-confirmed source. Append-only. No authenticated direct DML grant; narrow atomic owner-bound RPC serializes on the medication row.
- `adherence_barriers`: immutable patient report, category, occurrence time, regimen reference, chosen action and optional owned follow-up. Same-user INSERT/SELECT; changed-payload retry is rejected.
- `medication_care_tasks`: medication-related category, explicitly supplied date, source, status, version and bounded append-only transition history including original notes/date. Owner-readable; narrow create/update RPCs bind `auth.uid()` and enforce optimistic version checks.023 rejects changed dates/notes under a reused human task creation key. Repeated derived refill reconciliation remains idempotent.
- Existing `health_observations`: optional validated type/value/unit/secondary BP value. Existing descriptive notes remain `kind=note`.
- Existing `notification_deliveries`: alternate owned task reference, exclusive task/dose source constraint and task/device/time uniqueness. Patients still have SELECT only. No second notification queue or scheduler.

All three new tables use ENABLE + FORCE RLS and same-owner foreign keys. RPCs are narrow `SECURITY DEFINER` transactions with an empty search path, mandatory `auth.uid()`, explicit owner predicates and no caller-supplied owner. Patient repositories never use service keys or administrative connections. SQL functions cannot alter regimens/dose events. Rollback scripts are for disposable environments only; none were executed.023 rollback restores022's function; remove022 only after disposing of its new data in a separate approved process.

## Stock semantics

`Printed label quantity ≠ confirmed physical stock ≠ estimated remaining`. Single-product source evidence can be shown alongside inventory with its original line/source/review state; it never initializes stock. Multi-product label quantity needs an explicit product mapping and is not imported automatically.

Only tablet/capsule count units are supported. Strength in mg is never converted to counts. A first physical count is required before refill/adjustment; refill and removal amounts are positive, manual corrections are signed, negative ledger balances and unit changes are rejected. Transactions are retained. Reconfirming a physical count establishes a new estimation baseline.

Estimated remaining = latest ledger balance − compatible **reported taken** quantities since the last physical count, floored at zero. Not-taken/unsure/unrecorded schedules do not deduct units. This can overestimate real stock when consumption was not reported: patients can recount at any time. No automatic physical-stock deduction or ingestion claim is made.

Daily demand uses only one applicable active, reviewed timed version, known count dose, explicit times and matching units. Weekly demand is a seven-day average, not a precise exhaustion date. PRN, interval/unknown schedules, pending/future/ended courses and unsupported units return no daily estimate. Stored dose-rule timezones take precedence over changed display preferences; IANA date boundaries are used. The estimate does not extend the regimen/course.

Confirmed stock writes reconcile low-stock review tasks after the atomic ledger write. Existing in-app reminder presentation ticks also call the idempotent `/care-tasks/refresh` projection, so compatible new reports/retirement are reflected. If follow-up reconciliation fails after a ledger commit, retry the same stock ID or refresh; the ledger will not duplicate. Cancelled/completed supply tasks are retained and do not repeatedly reopen for the same stock revision. Refill closes an applicable resolved supply task; ended/inapplicable plans cancel derived supply tasks at reconciliation and suppress them immediately from actionable queries.

## Barriers, observations and review

Categories are patient statements, never diagnoses: forgetfulness, supply, symptom concern, timing, unclear instructions, complexity, unsure, other or prefer not to say. A saved barrier can reference the same patient's regimen and follow-up. Chosen support action is explicit; no extra dose or clinical instruction is generated. An erroneous report can be corrected by a new explanatory report; original barrier/stock events are retained.

Numeric observations validate compatible units (BP mmHg with both readings, glucose mmol/L or mg/dL, weight kg, sleep hours, patient mood score). Editing uses the existing observation API. No glucose unit conversion or clinical target comparison is performed.

Review combines calendar week/month-to-date dose/regimen summaries with rolling7/30-day observations/barriers, current inventory and open tasks. The UI labels these scopes. Trends group identical type/unit, show actual timestamps/count/difference and irregular sampling; fewer than two values means no change estimate. No percentage adherence denominator or drug-effect causality is invented. Dose reports and stored generated occurrences are distinct; unrecorded is not missed. Source records include version/state/source ID/review status without upgrading patient review to professional verification.

Records → Medication review preparation exports locally generated text, including the patient's editable extra questions, measurements and follow-ups. Nothing is automatically shared. Exported extra questions are local draft content, not a new permanent medical fact. No generic preventive screening/vaccine/lifestyle recommendation system is exposed.

The actual text download names each available medication beside its stock estimate and includes source IDs/review state. Missing clock times display as unspecified unless the regimen explicitly has `is_prn=true`; an incomplete schedule is never relabelled PRN. Focused frontend tests read the generated Blob, verify medication/stock/source/questions, and assert that exporting performs no patient write. These final presentation/export fixes have LOCAL/MOCK verification; the recorded real-browser journeys and screenshots precede this last text-only refinement.

## Agent tools and confirmations

The existing stateless Gemini Interactions architecture is unchanged. Added exact function names:

`get_medication_inventory`, `get_adherence_history`, `get_health_observations`, `get_longitudinal_summary`, `prepare_medication_review`, `get_unresolved_follow_ups`, `prepare_stock_change`, `prepare_adherence_barrier`, `prepare_medication_care_task`, `prepare_care_task_update`.

`clarify_medication_care` adds a controlled one-question tool for missing medicine, count/unit, follow-up date/type, barrier time or chosen support. Its bounded `care_clarification` marker is stored separately from dose medication-choice clarification; no patient fact or reference ID is invented. Existing context version1 accepts the optional marker; older stored sessions remain readable. A matched current application is required when rolling back code that reads newer context fields. Server time and patient timezone are injected metadata, never a hidden global clock.

Visit preparation requires the full medication-review tool. A narrow follow-up read cannot silently satisfy a combined medication/symptom request: within the existing four-round limit, the backend requests one coverage repair; persistent incomplete coverage fails safely. Once a full review is verified, a later narrow read cannot erase its observations/supply evidence. Human proposal/clarification messages retain priority over read summaries. A real F acceptance uncovered this missing-symptom branch; a regression covers both full-then-narrow order and bounded narrow-first repair.

Care tasks currently have one confirmed due date. Recurring non-dose monitoring requires separate confirmed tasks; a generic recurrence engine is not implemented. Observation windows retain the existing500-record cap, while care-ledger reads verify bounded complete pagination and fail closed above their limit.

Tools validate strict schemas without owner, credential or `confirmed` arguments. Reads query current persistence on each new session. Preparation returns `CareReview` with confirmation false; only the shared human review sheet calls the confirmed HTTP write. IDs are tool/application checked, recent turns remain bounded and factual replies use deterministic grounded summaries. Model context contains selected sections (at most five items, six points per trend) rather than the ledger/database. Existing four-tool budget, provider quota and B14 remain unchanged. New traces use `get_long_term_care` / `prepare_care_action` audit groups; HTTP tool payload names identify the exact function. Trace storage excludes patient content.

## Reproducible acceptance (中文)

Review aggregation uses report timestamps for reported taken/not taken/unsure
counts. The medication summary is calendar-week/month-to-date in the patient's
timezone; numeric observations use rolling7/30days. Only actually materialised
occurrences contribute to `recorded_occurrences` and `without_report`;
ungenerated historical schedules are not reconstructed. No adherence percentage
is inferred from these distinct populations. Test
`tests/backend/test_release_scenarios.py` exercises five synthetic days through
Application HTTP and B14 with injected local time. The separate opt-in
`test_release_live.py` uses real current-time database confirmations; it does
not pretend to backdate live challenges or establish multi-day live intake.

使用同一浏览器中的合成匿名账户，完成 Guide 或明确 Skip；不要清空 Auth。

1. **E**：手动登记 `DEMO Metformin 500 mg`，每次 **1 tablet**，20:00；核对来源并明确激活。
2. 药物详情 → 库存与补药：确认实际盘点2片、阈值7；确认前无流水，取消无变化。确认后显示估算余量2及补药任务。刷新后重选药物核对。
3. Today 助手询问库存；检查真实工具记录。请求准备盘点变动，查看待审核 sheet，明确确认后才保存。
4. 登记补药30片并确认；估算余量32，供药任务完成。重复同一个提交 ID 不增加流水；改数量重用该 ID 应拒绝。
5. Records → 用药困难：自述“药快用完”，选择已联系药房等措施并确认。原始报告保留，不自动当作漏服。
6. **F**：向 Today 助手说明“药剂师让我下周复查用药”，提供明确日期、时间及关联药物；Agent 应提出待核对任务，确认前无写入。点击审核并确认保存。也可通过 Today → 用药跟进使用同一服务登记。
7. Records → 健康记录：分别记录两天的合成BP130/80及125/80mmHg，每条明确确认；可编辑纠正。
8. 保留患者登录身份，新建 Agent 会话后请求准备复查；应读取已保存的困难、库存和未完成复查，不能依靠旧对话。
9. Records → 就诊与用药复查准备：检查来源、状态、未记录剂次、两次观测及变化−5mmHg、待办；补充自己的问题后实际下载文本。自己决定是否分享。
10. User B 无法读取/改写 User A 的库存、障碍、任务或观察；停用计划后不再显示/发送旧的供药任务。任何路径都不产生未经B14确认的服药事件。

11. 继续 **F**：告诉助手已完成该复查，要求准备完成任务；Agent 查询原任务后提出状态变更，审核并确认后才显示完成。展开历史可见原始 open 及 completed 两次状态。延期、取消使用同一确认流程；尚未提供日期时应先追问，不能猜测。

真实 F Agent 验证已通过上述创建、跨会话读取症状/任务及完成步骤。截图：`outputs/long-term-followup/`；该测试没有实际预约、发送通知或记录服药。受控缺失字段追问目前仅通过 LOCAL/MOCK 测试。

Automated commands and exact current results are in [workflow documentation](WORKFLOWS.md). Physical voice, calendar import and real-device Push remain separate manual gates. `e2e/long-term-care.spec.ts` uses real UI/Supabase; Gemini calls require a second opt-in. No preset successful Agent response is used.
