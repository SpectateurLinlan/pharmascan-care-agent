# contracts

跨业务纯契约、错误类型和基础能力；不依赖 UI、app、feature 或 HTTP。

| 文件 | 职责 |
|---|---|
| [notifications.ts](notifications.ts) | 设备绑定和推送订阅 DTO |
| [observations.ts](observations.ts) | 健康测量/观察和回顾 DTO，避免类型循环 |
| [preferences.ts](preferences.ts) | 偏好 DTO 与允许更新字段 |
| [routes.ts](routes.ts) | 纯导航目标、父级和有效性判断 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
