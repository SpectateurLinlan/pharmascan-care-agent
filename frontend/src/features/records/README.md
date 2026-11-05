# records

历史记录、筛选、周期总结与导出。

| 文件 | 职责 |
|---|---|
| [historyFilterLabels.ts](historyFilterLabels.ts) | 历史筛选名称和计划标签 |
| [HistoryScreen.tsx](HistoryScreen.tsx) | 患者剂次历史查询页面 |
| [recordHistoryPresentation.ts](recordHistoryPresentation.ts) | 历史记录状态的用户语言展示 |
| [RecordsOverview.tsx](RecordsOverview.tsx) | 记录导航及历史待补记入口 |
| [ReviewSummaryScreen.tsx](ReviewSummaryScreen.tsx) | 周/月/选定计划总结与导出 |
| [SummaryOverview.tsx](SummaryOverview.tsx) | 已有记录总结的共享展示 |
| [summaryPresentation.ts](summaryPresentation.ts) | 观察和记录总结的纯格式化 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
