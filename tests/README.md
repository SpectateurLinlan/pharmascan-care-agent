# Python 验证

| 位置 | 内容 |
|---|---|
| [backend/](backend/README.md) | 应用/领域/HTTP/权限与工作流回归；部分真实 SQL/provider 测试单独 opt-in |
| [fixtures/](fixtures/README.md) | synthetic 数据与许可明确的公开接口回放 |
| `test_start_dev.py` | 一键启动器的参数、端口、重载和进程管理 |
| `test_repository_structure.py` | 脚本根路径与源码入口的离线检查，不运行运维工具 |
| `test_packaging.py` | Python 包发现和版本化资源打包 |
| `test_migrations.py`、`test_migration_002_agent_enum_gaps.py` | SQL 文本/契约检查；执行 SQL 的测试另有独立开关 |
| `test_file_catalog.py` | 本地目录索引维护工具 |
| `test_startup_summary.py` | 启动测量报告整理 |

从仓库根目录使用 `PYTHONPATH=backend` 和现有虚拟环境运行指定 pytest 文件。
前端 Vitest 在 frontend/src，Playwright 在 frontend/e2e；不要将不同证据类型混为真实环境验收。
