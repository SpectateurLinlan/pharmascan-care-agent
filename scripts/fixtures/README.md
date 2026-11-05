# fixtures

只生成 synthetic/demo_only 测试素材，不模拟真实识别成功。
从仓库根目录用 `python scripts/fixtures/文件.py` 执行指定 Python 工具。

| 文件 | 职责与副作用 |
|---|---|
| [generate_gallery_demo.py](generate_gallery_demo.py) | 生成 demo_only 药物标签/药片素材到 outputs，不调用 provider |

真实 SQL、患者写入、密钥生成、外部调用和通知发送遵守项目的独立授权边界。此说明不是执行授权。
