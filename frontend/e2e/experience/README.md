# 页面、导航与整体体验

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [applicationFlows.spec.ts](applicationFlows.spec.ts) | 录入、设置、聊天、提醒等跨页面一致性 | 见文件头和测试数据装配；不自动启用真实服务 |
| [localNavigation.spec.ts](localNavigation.spec.ts) | 当前导航、聊天草稿与日历导出（本地内存 API） | `RUN_LOCAL_UX` |
| [onboardingGuide.spec.ts](onboardingGuide.spec.ts) | 当前六步引导的操作、返回和中英文布局 | 见文件头和测试数据装配；不自动启用真实服务 |
| [patientExperience.spec.ts](patientExperience.spec.ts) | 真实环境中的用药、健康记录与总结流程 | `RUN_LIVE_BROWSER` |
| [patientFeedback.spec.ts](patientFeedback.spec.ts) | 账户、图片同意、核对和聊天界面 | 见文件头和测试数据装配；不自动启用真实服务 |
| [reminderActivation.spec.ts](reminderActivation.spec.ts) | 提醒、跨标签页抑制和延后处理 | 见文件头和测试数据装配；不自动启用真实服务 |
| [responsiveDensity.spec.ts](responsiveDensity.spec.ts) | 页面密度、长内容、大字、横屏和缩放 | 见文件头和测试数据装配；不自动启用真实服务 |
| [responsiveLayout.spec.ts](responsiveLayout.spec.ts) | 根页面栅格、内容数量、对齐与账户布局 | 见文件头和测试数据装配；不自动启用真实服务 |
| [todayAssistantNavigation.spec.ts](todayAssistantNavigation.spec.ts) | 今日页面与 Assistant 的导航 | 见文件头和测试数据装配；不自动启用真实服务 |
| [voiceAgentJourney.spec.ts](voiceAgentJourney.spec.ts) | 语音输入、Agent 与播放同意的完整演示 | `RUN_LIVE_BROWSER` |
| [workspaceLayout.spec.ts](workspaceLayout.spec.ts) | Assistant 工作区、历史栏和底部操作 | 见文件头和测试数据装配；不自动启用真实服务 |
