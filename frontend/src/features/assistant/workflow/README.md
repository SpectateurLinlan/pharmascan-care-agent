# Assistant workflow

聊天、回答依据及应用工作流交互；通过各业务公开表单推进操作。

| 文件 | 职责 |
|---|---|
| [AssistantAccountActions.tsx](AssistantAccountActions.tsx) | 复用账户交互，身份变化后刷新 |
| [AssistantCareActions.tsx](AssistantCareActions.tsx) | 照护工作流复核和办理入口 |
| [AssistantCareFields.tsx](AssistantCareFields.tsx) | 观察、库存、困难、跟进字段收集 |
| [AssistantDoseReportActions.tsx](AssistantDoseReportActions.tsx) | 服药状态报告的独立确认入口 |
| [AssistantEnrollmentFields.tsx](AssistantEnrollmentFields.tsx) | Assistant 录入缺失字段收集 |
| [AssistantFeedbackActions.tsx](AssistantFeedbackActions.tsx) | 反馈内容收集与独立确认 |
| [AssistantImageCompare.tsx](AssistantImageCompare.tsx) | 独立原图与参考图比较交互 |
| [AssistantKnowledgeActions.tsx](AssistantKnowledgeActions.tsx) | 药物知识办理、名称澄清与来源展示 |
| [AssistantLateReportActions.tsx](AssistantLateReportActions.tsx) | 受限历史补记及更正入口 |
| [AssistantMediaActions.css](AssistantMediaActions.css) | Assistant 文件管理局部样式 |
| [AssistantMediaActions.tsx](AssistantMediaActions.tsx) | 图库/PDF 列表与文件动作 |
| [AssistantMediaLifecycle.tsx](AssistantMediaLifecycle.tsx) | 文件资料更正、移除、退役和删除确认 |
| [AssistantMedicationActions.tsx](AssistantMedicationActions.tsx) | 药物资料和用药计划办理 |
| [AssistantNotificationActions.tsx](AssistantNotificationActions.tsx) | 当前设备或全部设备的通知办理 |
| [AssistantPdfUpload.tsx](AssistantPdfUpload.tsx) | 工作流 PDF 校验、上传和草稿恢复 |
| [AssistantPhotoUpload.tsx](AssistantPhotoUpload.tsx) | 工作流照片上传、许可与失败保留 |
| [AssistantProgress.tsx](AssistantProgress.tsx) | 任务执行进度、取消和失败状态 |
| [AssistantRecordActions.tsx](AssistantRecordActions.tsx) | 已有记录查询和总结入口 |
| [AssistantReminderActions.tsx](AssistantReminderActions.tsx) | 提醒读取及日历导出 |
| [AssistantReminderChanges.tsx](AssistantReminderChanges.tsx) | 提醒偏好更改复核 |
| [AssistantSettingsActions.tsx](AssistantSettingsActions.tsx) | 偏好设置复核及保存 |
| [AssistantSourceActions.tsx](AssistantSourceActions.tsx) | 来源文件审阅与指令核对 |
| [AssistantSourcePreview.tsx](AssistantSourcePreview.tsx) | 从聊天打开来源预览 |
| [AssistantSupportActions.tsx](AssistantSupportActions.tsx) | 导航、会话、引导、语音等客户端动作契约与交互 |
| [AssistantWorkflow.tsx](AssistantWorkflow.tsx) | 按能力派发复用表单，保留独立患者确认 |
| [AssistantWorkflowOriginals.tsx](AssistantWorkflowOriginals.tsx) | 草稿原图的保存/撤销与状态展示 |

同目录 `*.test.ts(x)` 为 synthetic 本地回归；表单提交继续使用既有独立确认。
