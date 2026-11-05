# 集成参考

`pharmascan_api.py` 是外部 Stage2 接口/兼容性说明，不是客户端生产入口。
生产适配器位于 app/infrastructure；冻结 OpenAPI 位于 docs/external。
不得在这里修改外部模型、权重或 owner 仓库。
