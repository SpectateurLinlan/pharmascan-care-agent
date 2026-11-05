# 业务功能

每个目录拥有自己的页面、表单和模型，测试就近放置。
跨业务仅使用 `frontend/architecture.config.mjs` 声明的公开模块，不新增总导出桶。
Assistant 可复用业务入口，普通功能不依赖 Assistant；会话浏览独立归 conversations。

| 目录 | 职责 |
|---|---|
| [assistant/](assistant/README.md) | 聊天、回答依据及应用工作流交互；通过各业务公开表单推进操作。 |
| [conversations/](conversations/README.md) | 账户和 Assistant 共用的会话浏览；独立归属以避免账户反向依赖 Assistant。 |
| [enrollment/](enrollment/README.md) | 手动或来源录入、待核对字段与纯草稿复核。 |
| [medications/](medications/README.md) | 药物列表/详情、计划版本与停止计划。 |
| [media/](media/README.md) | 照片、原始来源、图库、PDF 和图像对比。 |
| [today/](today/README.md) | 今日剂次展示及患者状态报告。 |
| [records/](records/README.md) | 历史记录、筛选、周期总结与导出。 |
| [care/](care/README.md) | 健康观察、库存、困难及跟进事项。 |
| [account/](account/README.md) | 账户、资料、联系人、设置、隐私和反馈。 |
| [reminders/](reminders/README.md) | 提醒与设备通知的业务装配；通过 platform 适配浏览器能力。 |
| [onboarding/](onboarding/README.md) | 首次使用引导及按用户保存的进度。 |
