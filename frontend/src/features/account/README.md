# account

账户、资料、联系人、设置、隐私和反馈。

| 文件 | 职责 |
|---|---|
| [accountPresentation.ts](accountPresentation.ts) | 账户显示名称的纯格式化 |
| [CaregiverDetailsFields.tsx](CaregiverDetailsFields.tsx) | 联系人资料及保存许可字段 |
| [CaregiversScreen.tsx](CaregiversScreen.tsx) | 未验证联系人管理 |
| [FeedbackFields.tsx](FeedbackFields.tsx) | 反馈分类与文本字段 |
| [FeedbackScreen.tsx](FeedbackScreen.tsx) | 反馈页面装配 |
| [HeaderAccountButton.tsx](HeaderAccountButton.tsx) | 顶部账户状态入口 |
| [MeScreen.tsx](MeScreen.tsx) | 账户登录/关联/密码/退出交互 |
| [PatientHub.tsx](PatientHub.tsx) | 我的入口、资料和隐私/关于等信息页面 |
| [SettingsScreen.tsx](SettingsScreen.tsx) | 语言、语音、隐私和辅助设置页面 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
