# errors

跨业务纯契约、错误类型和基础能力；不依赖 UI、app、feature 或 HTTP。

| 文件 | 职责 |
|---|---|
| [apiError.ts](apiError.ts) | 同一 ApiError 构造器与错误 DTO，无网络依赖 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
