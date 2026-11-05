# 语言与偏好

纯词典/翻译及偏好上下文；应用从 app 注入 PreferencesPort。

## 子目录

| 目录 | 内容 |
|---|---|
| [messages/](messages/README.md) | 按领域词典及按原顺序注册的 catalog |

| 文件 | 职责 |
|---|---|
| [language.tsx](language.tsx) | 语言/偏好上下文，持久化由 typed port 注入 |
| [preferencesPort.ts](preferencesPort.ts) | 偏好读取/保存端口；不构造 HTTP 客户端 |
| [translation.ts](translation.ts) | 纯翻译查找和原有覆盖优先级 |
| [types.ts](types.ts) | 模块公开类型 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
