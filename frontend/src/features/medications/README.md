# medications

药物列表/详情、计划版本与停止计划。

| 文件 | 职责 |
|---|---|
| [MedicationList.tsx](MedicationList.tsx) | 药物条目展示与操作意图 |
| [MedicinesHub.tsx](MedicinesHub.tsx) | 当前/历史药物列表和选定药物详情 |
| [regimenHistoryModel.ts](regimenHistoryModel.ts) | 计划状态与疗程分组的纯模型 |
| [RegimenHistoryScreen.tsx](RegimenHistoryScreen.tsx) | 计划版本与历史指令页面 |
| [regimenPresentation.ts](regimenPresentation.ts) | 已核对计划的剂量、时间和疗程展示 |
| [StopPlanReview.tsx](StopPlanReview.tsx) | 停止计划的复核展示 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
