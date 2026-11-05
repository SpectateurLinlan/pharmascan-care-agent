# operations

数据库/密钥等运维工具；目录位置不授予执行权限。
从仓库根目录用 `python scripts/operations/文件.py` 执行指定 Python 工具。

| 文件 | 职责与副作用 |
|---|---|
| [create_vapid_keys.py](create_vapid_keys.py) | 创建本地密钥文件；不显示密钥、不启用发送，执行需明确意图 |
| [db.py](db.py) | 数据库状态、迁移和只读报告；迁移写入需独立授权 |

真实 SQL、患者写入、密钥生成、外部调用和通知发送遵守项目的独立授权边界。此说明不是执行授权。
