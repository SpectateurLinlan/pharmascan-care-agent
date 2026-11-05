# care

健康观察、库存、困难及跟进事项。

| 文件 | 职责 |
|---|---|
| [AdherenceBarriersScreen.tsx](AdherenceBarriersScreen.tsx) | 用药困难记录页面 |
| [CareReviewSheet.tsx](CareReviewSheet.tsx) | 库存/困难/跟进操作的共享独立确认 |
| [careTaskCalendar.ts](careTaskCalendar.ts) | 跟进日期/状态筛选与日历模型 |
| [CareTaskForm.tsx](CareTaskForm.tsx) | 跟进事项字段和提醒输入 |
| [CareTasksScreen.tsx](CareTasksScreen.tsx) | 跟进列表、状态变更与日历视图 |
| [followUpCopy.ts](followUpCopy.ts) | 照护及补记状态文案 |
| [FollowUpError.tsx](FollowUpError.tsx) | 照护/历史报告失败的安全展示 |
| [HealthTrackingScreen.tsx](HealthTrackingScreen.tsx) | 健康感受/测量记录与复核；含复用测量字段 |
| [InventoryPanel.tsx](InventoryPanel.tsx) | 实物盘点、补货及数量调整 |
| [LateDoseFollowUps.tsx](LateDoseFollowUps.tsx) | 受限历史报告、补记、复核与更正 |
| [MedicationDifficultiesPanel.tsx](MedicationDifficultiesPanel.tsx) | 用药困难和支持措施 |
| [MedicationReviewScreen.tsx](MedicationReviewScreen.tsx) | 药物相关综合回顾 |
| [ObservationReviewSheet.tsx](ObservationReviewSheet.tsx) | 健康观察保存/删除的共享复核 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
