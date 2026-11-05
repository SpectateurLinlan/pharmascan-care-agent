# 照护与跟进

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [longTermCare.spec.ts](longTermCare.spec.ts) | 长期照护完整演示；独立真实环境开关 | `RUN_GEMINI_CARE_DEMO`、`RUN_GEMINI_FOLLOWUP_DEMO`、`RUN_LONG_TERM_DEMO` |
| [todayCareCalendarUi.spec.ts](todayCareCalendarUi.spec.ts) | 今日跟进、照护表单、日历与大字布局 | 见文件头和测试数据装配；不自动启用真实服务 |
| [todayCareFollowups.spec.ts](todayCareFollowups.spec.ts) | 跟进深链、历史确认和能力关闭状态 | 见文件头和测试数据装配；不自动启用真实服务 |
