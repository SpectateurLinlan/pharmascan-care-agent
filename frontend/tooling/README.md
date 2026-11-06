# 工程检查

| 文件 | 用途 |
|---|---|
| architecture.mjs | 用 TypeScript AST 解析静态、动态和 type-only 依赖，检查大小写、公开边界及循环；核对 E2E 页面和浏览器模块地址（含查询参数） |
| architecture.test.mjs | 用非法与合法虚拟源码图验证检查器，不执行应用或外部服务 |

从 frontend 运行 `npm run check:architecture`；规则来源是 ../architecture.config.mjs。
不允许通过全目录通配导出或忽略错误来绕过新产生的边界问题。
新增 feature 必须先在配置中声明归属与公开入口；无法静态确定目标的动态 import 会报错。

`startupResources.test.mjs`：用生产构建检查首屏静态依赖总量和按需界面边界；运行 `npm run check:startup`。只读取构建内存，不调用业务 API，也不输出源码或环境值。
