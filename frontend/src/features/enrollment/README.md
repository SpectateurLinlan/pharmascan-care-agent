# enrollment

手动或来源录入、待核对字段与纯草稿复核。

| 文件 | 职责 |
|---|---|
| [DeleteDraftReview.tsx](DeleteDraftReview.tsx) | 纯草稿删除的独立复核 |
| [EnrollScreen.tsx](EnrollScreen.tsx) | 手动用药资料/计划录入和既有复核流程 |
| [EvidenceEnrollmentScreen.tsx](EvidenceEnrollmentScreen.tsx) | 来源证据录入的页面装配 |
| [EvidencePlanFields.tsx](EvidencePlanFields.tsx) | 来源计划字段展示和患者核对 |
| [MedicationInputs.tsx](MedicationInputs.tsx) | 日期、时间和多时点输入控件 |
| [medicationSetup.ts](medicationSetup.ts) | 待核对来源与草稿的统一入口模型 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
