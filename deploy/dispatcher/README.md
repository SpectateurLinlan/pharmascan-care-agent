# dispatcher

index.py 是隔离的 Vercel Push Dispatcher ASGI 入口。只组装 worker 依赖，不共享患者 API 的身份或前端环境。

完整服务根、构建和部署规则见 [上级说明](../README.md)。读取配置不授权部署、发送或云端变更。
