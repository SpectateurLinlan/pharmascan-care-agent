# maintenance

文件整理和本地索引维护；保留检查模式与显式执行边界。
从仓库根目录用 `python scripts/maintenance/文件.py` 执行指定 Python 工具。

| 文件 | 职责与副作用 |
|---|---|
| [consolidate_repository.py](consolidate_repository.py) | 保守仓库维护；默认检查，--apply 才执行有边界的整理 |
| [update_file_catalog.py](update_file_catalog.py) | 生成/检查私有本地文件索引，不作为公开发布物 |

真实 SQL、患者写入、密钥生成、外部调用和通知发送遵守项目的独立授权边界。此说明不是执行授权。
