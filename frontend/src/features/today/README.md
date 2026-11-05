# today

今日剂次展示及患者状态报告。

| 文件 | 职责 |
|---|---|
| [CompactDoseCard.tsx](CompactDoseCard.tsx) | 紧凑剂次显示 |
| [ConfirmReportSheet.tsx](ConfirmReportSheet.tsx) | 患者报告 taken/not taken/unsure 的复核 |
| [DoseDetails.tsx](DoseDetails.tsx) | 剂次与已核对指令详情 |
| [ReportDetails.tsx](ReportDetails.tsx) | 报告数量、范围及未知信息说明 |
| [TodayAttentionOverview.tsx](TodayAttentionOverview.tsx) | 今日待办与用药关注点 |
| [TodayMedicationCarousel.tsx](TodayMedicationCarousel.tsx) | 今日药物概览与选定详情 |
| [TodayScreen.tsx](TodayScreen.tsx) | 今日剂次、患者状态选择和独立确认 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
