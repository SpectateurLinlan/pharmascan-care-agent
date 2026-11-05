# Assistant

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [capabilities.spec.ts](capabilities.spec.ts) | 能力目录、恢复任务和独立确认 | 见文件头和测试数据装配；不自动启用真实服务 |
| [care.spec.ts](care.spec.ts) | 健康观察、库存、困难和跟进办理 | 见文件头和测试数据装配；不自动启用真实服务 |
| [conversationSupport.spec.ts](conversationSupport.spec.ts) | 会话选择、历史和上下文支持 | 见文件头和测试数据装配；不自动启用真实服务 |
| [conversationThreads.spec.ts](conversationThreads.spec.ts) | 会话线程和持久化 | 见文件头和测试数据装配；不自动启用真实服务 |
| [enrollment.spec.ts](enrollment.spec.ts) | 药物录入与字段收集 | 见文件头和测试数据装配；不自动启用真实服务 |
| [imageCompare.spec.ts](imageCompare.spec.ts) | 照片比较与证据边界 | 见文件头和测试数据装配；不自动启用真实服务 |
| [knowledge.spec.ts](knowledge.spec.ts) | 药物知识查询、名称澄清及独立办理入口 | 见文件头和测试数据装配；不自动启用真实服务 |
| [media.spec.ts](media.spec.ts) | 媒体查看、预览和办理入口 | 见文件头和测试数据装配；不自动启用真实服务 |
| [mediaLifecycle.spec.ts](mediaLifecycle.spec.ts) | 照片/PDF 的修改与删除 | 见文件头和测试数据装配；不自动启用真实服务 |
| [medicationChoices.spec.ts](medicationChoices.spec.ts) | 药物候选选择、意图继续和过期处理 | 见文件头和测试数据装配；不自动启用真实服务 |
| [notificationDevices.spec.ts](notificationDevices.spec.ts) | 通知设备和绑定管理 | 见文件头和测试数据装配；不自动启用真实服务 |
| [patientAnswers.spec.ts](patientAnswers.spec.ts) | 患者可读回答及来源 | 见文件头和测试数据装配；不自动启用真实服务 |
| [pdfUpload.spec.ts](pdfUpload.spec.ts) | PDF 上传与草稿恢复 | 见文件头和测试数据装配；不自动启用真实服务 |
| [planChange.spec.ts](planChange.spec.ts) | 计划修改、核对与确认 | 见文件头和测试数据装配；不自动启用真实服务 |
| [progress.spec.ts](progress.spec.ts) | 处理中状态和进度反馈 | 见文件头和测试数据装配；不自动启用真实服务 |
| [records.spec.ts](records.spec.ts) | 记录查询、服药报告、补记和更正 | 见文件头和测试数据装配；不自动启用真实服务 |
| [referenceUpload.spec.ts](referenceUpload.spec.ts) | 参考照片上传 | 见文件头和测试数据装配；不自动启用真实服务 |
| [reminders.spec.ts](reminders.spec.ts) | 提醒读取、修改与独立确认 | 见文件头和测试数据装配；不自动启用真实服务 |
| [settingsContacts.spec.ts](settingsContacts.spec.ts) | 设置、照护联系人和授权界面 | 见文件头和测试数据装配；不自动启用真实服务 |
| [sources.spec.ts](sources.spec.ts) | 来源选择、私有预览和证据显示 | 见文件头和测试数据装配；不自动启用真实服务 |
| [workflowOriginals.spec.ts](workflowOriginals.spec.ts) | 工作流原图保留及清理 | 见文件头和测试数据装配；不自动启用真实服务 |
| [workflows.spec.ts](workflows.spec.ts) | 办理任务与跨步骤恢复 | 见文件头和测试数据装配；不自动启用真实服务 |
