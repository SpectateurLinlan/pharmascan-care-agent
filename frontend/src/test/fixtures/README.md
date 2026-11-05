# fixtures

Vitest setup、synthetic fixtures 和跨 feature 的应用集成测试，不进入生产入口。

| 文件 | 职责 |
|---|---|
| [historyTestFixture.ts](historyTestFixture.ts) | 跨页面 synthetic 历史记录夹具 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
