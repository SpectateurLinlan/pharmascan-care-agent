# 脚本入口

日常一键启动：`python scripts/start_dev.py`。后端/前端端口可通过参数指定，默认 8001/5173。
环境和依赖准备见 [开发指南](../docs/DEVELOPMENT.md)。

| 根层入口 | 用途 |
|---|---|
| [start_dev.py](start_dev.py) | 单终端启动已有 FastAPI + Vite；检查端口并管理本次启动的子进程 |
| [run_patient_api.py](run_patient_api.py) | Render 患者 API 入口及离线资源检查；不启动特权 worker |
| [run_reminders.py](run_reminders.py) | 独立提醒 worker 的显式启动入口；涉及发送，不作为默认开发启动 |

| 子目录 | 内容 |
|---|---|
| [operations/](operations/README.md) | 数据库/密钥等运维工具；目录位置不授予执行权限。 |
| [qa/](qa/README.md) | 验收、诊断与发布核验；按文件区分离线、只读和写入/外部调用。 |
| [fixtures/](fixtures/README.md) | 只生成 synthetic/demo_only 测试素材，不模拟真实识别成功。 |
| [maintenance/](maintenance/README.md) | 文件整理和本地索引维护；保留检查模式与显式执行边界。 |

不要把启动、数据库变更、通知发送合并成一个默认脚本。生产入口和验收入口分离；不要默认加载全部 qa 工具。

## 为什么保留这些工具

启动入口由开发/部署显式调用；QA/运维工具是手动入口，不被应用 import 并不代表无用。
`database_contracts.py` 是 QA 共享辅助，其余工具按子目录表中的目标独立使用。
本轮没有发现可仅凭静态引用判定无用的运维工具，故保留独立权限、失败处理和 CLI。
备份、迁移、验收、密钥和通知不合成一个默认执行脚本；它们的权限与副作用不同。
`maintenance/` 是可选维护工具，不参与开发启动；`fixtures/` 只生成测试素材。

Python 工具统一使用 Ruff 排版；浏览器诊断 JS 使用前端 format/format:check。
内部完整审计记录列出逐文件用途和引用证据；手动工具的“有用途”不等于“最近已执行”。
