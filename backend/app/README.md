# 后端组件

`config.py` 解析并验证配置；服务在 transport composition root 显式组装。
跨组件使用公开接口与 DTO，不传递私有仓库实现。

| 子目录 | 责任 |
|---|---|
| [agent/](agent/README.md) | 有界编排、能力注册、typed tools 和策略入口；不直接调用 SQL/私有仓库。 |
| [application/](application/README.md) | 用例、服务与业务工作流；通过显式端口访问持久化和外部能力。 |
| [contracts/](contracts/README.md) | 对外 DTO、Protocol 和状态枚举；跨组件交换明确类型。 |
| [domain/](domain/README.md) | 纯安全、剂量、库存和时间规则；不依赖 I/O 或 UI。 |
| [infrastructure/](infrastructure/README.md) | 内存/SQL/HTTP/provider/存储适配，实现在 contracts 中定义的端口。 |
| [transport/](transport/README.md) | 身份校验、HTTP 请求/响应、路由和 composition root；患者与 worker 分离。 |
| [resources/](resources/README.md) | 版本化药名等运行时 JSON 资源；由 Python 包打包。 |

详见 [架构与信任边界](../../docs/ARCHITECTURE.md)。纯目录整理不修改患者事实、SQL、RLS 或通知权限。
