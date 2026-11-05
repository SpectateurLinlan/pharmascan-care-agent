# notifications

语音、音频和通知适配；后端副作用通过显式端口注入。

| 文件 | 职责 |
|---|---|
| [reminders.ts](reminders.ts) | 浏览器标签页提醒端口；不提供后台可靠送达 |
| [webPush.ts](webPush.ts) | 浏览器推送适配/已授权后端装配，按目录所属边界划分 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
