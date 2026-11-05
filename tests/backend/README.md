# 后端回归与本地运行夹具

`test_*.py` 按业务职责命名：enrollment/dosing、care、medication knowledge、
assistant/workflow、media、Auth/RLS、storage、deployment 等。默认测试以 synthetic 内存/HTTP mock 为主。

| 文件族/子目录 | 作用 |
|---|---|
| `conftest.py` | 固定时钟、内存依赖和 synthetic 标识 |
| `fixtures/` | 带许可/来源的公开标签回放及 DEMO 图片/PDF |
| `assistant_*_runtime.py` | 显式本机验收 app factory；不是部署入口，不得公开暴露 |
| `test_*_sql*.py`、`*_real_sql.py` | SQL 静态或真实数据库检查，按文件声明的开关区分 |
| `accept_*.py` | 显式 provider/发布验收，不是默认单元测试 |

真实 SQL、provider、通知和设备调用只在具体目标得到批准后执行。
本地内存、公开回放、真实后端、真实数据库和部署验收分别报告。
