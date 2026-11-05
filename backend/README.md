# 后端

Python 包仍为 `app`，位于 backend/app；不改变现有部署和 PYTHONPATH。

| 子目录/文件 | 内容 |
|---|---|
| [app/](app/README.md) | 生产代码，各层责任与入口见该目录说明 |
| [integrations/](integrations/README.md) | 外部接口集成说明/兼容清单，不拥有 Stage2 模型 |
| [MEDICATION_UNDERSTANDING.md](MEDICATION_UNDERSTANDING.md) | 药物知识接口与覆盖限制 |

入口为 `app.transport.app_factory:create_app`；开发用 scripts/start_dev.py，部署入口见 deploy/README。
egg-info、__pycache__ 为生成产物；不应成为业务代码目录。
