# 共享基础与契约

跨业务纯契约、错误类型和基础能力；不依赖 UI、app、feature 或 HTTP。

## 子目录

| 目录 | 内容 |
|---|---|
| [contracts/](contracts/README.md) | 偏好、路由、观察与通知的纯 DTO |
| [errors/](errors/README.md) | 共享错误类型，无请求逻辑 |
| [privacy/](privacy/README.md) | 图片许可状态 |
| [time/](time/README.md) | 患者时区和日期时间转换 |

| 文件 | 职责 |
|---|---|
| [appMetadata.ts](appMetadata.ts) | 从 package.json 读取统一版本号 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
