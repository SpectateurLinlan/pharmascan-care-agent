# reminders

提醒与设备通知的业务装配；通过 platform 适配浏览器能力。

| 文件 | 职责 |
|---|---|
| [NotificationInvitation.tsx](NotificationInvitation.tsx) | 通知许可的主动选择提示 |
| [PushNotificationSettings.tsx](PushNotificationSettings.tsx) | 设备通知设置与独立患者操作 |
| [ReminderLeadSelect.tsx](ReminderLeadSelect.tsx) | 提醒提前量选择 |
| [ReminderMonitor.tsx](ReminderMonitor.tsx) | 应用活跃期间的剂次提醒监测 |
| [ReminderSettings.tsx](ReminderSettings.tsx) | 提醒偏好和日历导出页面 |
| [webPush.ts](webPush.ts) | 浏览器推送适配/已授权后端装配，按目录所属边界划分 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
