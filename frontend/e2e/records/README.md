# 记录与总结

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [confirmationGate.spec.ts](confirmationGate.spec.ts) | 未确认草稿不进入正式记录 | 见文件头和测试数据装配；不自动启用真实服务 |
| [functional.spec.ts](functional.spec.ts) | 真实本地 API 的记录过滤、分页和归属 | 见文件头和测试数据装配；不自动启用真实服务 |
| [historyPresentation.spec.ts](historyPresentation.spec.ts) | 记录读取失败、分页和计划范围 | 见文件头和测试数据装配；不自动启用真实服务 |
| [layout.spec.ts](layout.spec.ts) | 记录页面/子页面布局及报告展示与完整导出 | 见文件头和测试数据装配；不自动启用真实服务 |
| [releaseReview.spec.ts](releaseReview.spec.ts) | 指定五日时间线的事实总结与导出 | `RUN_RELEASE_BROWSER` |
| [releaseSummaryVoice.spec.ts](releaseSummaryVoice.spec.ts) | 总结事实、健康指标与取消语音后的恢复 | 见文件头和测试数据装配；不自动启用真实服务 |
| [today.spec.ts](today.spec.ts) | 今日待报告项、记录过滤和时间推进 | 见文件头和测试数据装配；不自动启用真实服务 |
