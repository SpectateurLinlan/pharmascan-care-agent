# 照护日历：后续只读集成边界

本轮仅定义 `backend/app/contracts/care_calendar.py` 中的只读 `CareCalendarEvent`，没有新增日历数据表、写入接口或生成历史剂次。

| 事件 | 可信来源 | 时间语义 | 点击目标 |
|---|---|---|---|
| 计划剂次 | DoseScheduleService / 已有 dose_occurrences、Records 只读查询 | due_at + 患者 IANA 时区；自述状态独立 | 原剂次详情 / 确认补记 |
| 用药跟进 | Care Task 公开查询 | due_at；未完成且已到期派生 overdue | `#care-tasks?task=...` |
| 疗程起止 | 已核对 RegimenVersion course_start_date / course_end_date | 只有日期，不转 UTC 午夜 | 原计划版本 |
| 版本生效起止 | RegimenVersion effective_from / effective_to | 真实 UTC 时间点，按患者时区显示 | 原计划版本 |

稳定标识为 source_type + source_id + kind；同一个计划版本可以有多种边界事件。药物、产品规格、计划版本和患者登记不合并。未记录不派生未服；PRN 不产生固定剂次。任务日期不等于医嘱日期。

建议后续限定为单月只读聚合：经过认证的应用服务调用现有公开服务，按患者本地日期计算 UTC 窗口；明确分页/上限/部分结果，保留来源标识。未来剂次由既有 schedule 规则投影，不在 GET 日历时批量写入，更不能补造过去剂次。需要纯只读的未来 schedule projection 公开接口后再接入未来月视图。

前端提供月份导航、选日清单和现有详情深链，不创建第二套状态或提醒队列；已结束/替换版本只显示真实有效区间。月份切换、DST、跨午夜、同日版本切换、PRN、无关联数据和 A/B 患者隔离需定向验收。AI 建议只能展示，患者显式确认后才进入已有写入流程。

预计边界：一个只读应用聚合服务和 GET DTO、一个月视图组件、已有详情入口与定向测试；不涉及生产历史回填、日历同步、自动预约或第二套药物提醒。

当前DTO中dose_occurrence的source_id必须是真实已有剂次ID。未来若接入尚未持久化的规则投影，应显式增加规则来源类型，并使用真实rule_id＋UTC计划时间生成稳定事件键；不能给虚拟事件伪造已保存剂次身份。该扩展与纯只读投影接口一并验收，不在当前GET路径写入计划记录。
