# 测试基础与跨业务回归

Vitest setup、synthetic fixtures 和跨 feature 的应用集成测试，不进入生产入口。

## 子目录

| 目录 | 内容 |
|---|---|
| [fixtures/](fixtures/README.md) | 跨模块 synthetic 数据 |
| [integration/](integration/README.md) | 真实 React 组件的跨业务本地测试 |

| 文件 | 职责 |
|---|---|
| [setupTests.ts](setupTests.ts) | Vitest 环境准备，阻止默认真实 Auth 注册 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
