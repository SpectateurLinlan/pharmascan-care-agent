# qa

验收、诊断与发布核验；按文件区分离线、只读和写入/外部调用。
从仓库根目录用 `python scripts/qa/文件.py` 执行指定 Python 工具。

| 文件 | 职责与副作用 |
|---|---|
| [check_supabase_test_target.py](check_supabase_test_target.py) | 核对隔离测试目标，防止把线上项目当作测试库 |
| [database_contracts.py](database_contracts.py) | 数据库验收对象和契约的共享辅助 |
| [db_integration.py](db_integration.py) | 真实数据库 synthetic 隔离验收，会创建/清理测试记录；需授权目标 |
| [eval_assistant.py](eval_assistant.py) | Assistant synthetic 能力/行为评估；额外 provider 模式显式选择 |
| [execute_release_migrations.py](execute_release_migrations.py) | 受授权的发布迁移执行器；不要在常规验证中运行 |
| [inspect_assistant_evidence_scope.py](inspect_assistant_evidence_scope.py) | 只读核对 Assistant 核验证据的范围 |
| [inspect_library_release.py](inspect_library_release.py) | 药物库发布验收的只读检查 |
| [medication_counts_in_browser.js](medication_counts_in_browser.js) | 浏览器控制台的只读药物/计划数量核对 |
| [pre_migration_backup.py](pre_migration_backup.py) | 迁移前备份到本地忽略目录；需授权目标及私有数据处理 |
| [render_release_evidence.py](render_release_evidence.py) | 将实际发布结果整理为证据，不生成虚假成功 |
| [run_assistant_acceptance.py](run_assistant_acceptance.py) | 按指定隔离 profile 执行 Assistant 验收；保留目标和写入授权边界 |
| [stage2_contract_diff.py](stage2_contract_diff.py) | 离线比较版本化 OpenAPI，更新 docs/external 差异文件 |
| [stage2_v010_smoke.py](stage2_v010_smoke.py) | 显式调用 Stage2 的 synthetic 服务探针；不是离线测试 |
| [summarize_startup.py](summarize_startup.py) | 离线整理启动测量指标 |

真实 SQL、患者写入、密钥生成、外部调用和通知发送遵守项目的独立授权边界。此说明不是执行授权。
