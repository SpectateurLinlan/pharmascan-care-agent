# MediThread 项目结构

按职责查找代码；每个大目录 README 进一步列出子目录、脚本和依赖规则。
接口和信任边界仍以 [ARCHITECTURE](ARCHITECTURE.md) 为准。

## 仓库入口

| 目录/文件 | 内容与维护入口 |
|---|---|
| [frontend/](../frontend/README.md) | React/TypeScript/Vite 患者界面与浏览器验收 |
| [backend/](../backend/README.md) | FastAPI、Agent、应用服务、纯规则及外部适配 |
| [scripts/](../scripts/README.md) | 稳定启动入口、运维、QA、素材和维护工具 |
| [tests/](../tests/README.md) | Python 单元、契约、布局和显式集成验收 |
| [supabase/](../supabase/README.md) | 有版本的迁移、回退和待审 SQL |
| [deploy/](../deploy/README.md) | 患者前端、患者 API 与独立 Dispatcher 的配置 |
| [docs/](README.md) | 公开架构、接口、开发及许可文档 |
| `pyproject.toml` | Python 依赖、包发现、lint/pytest 与 worker entrypoint |
| `vercel.json`、`.vercelignore` | 独立 Dispatcher 部署发现和打包过滤 |
| `.env.example` | 后端配置模板；真实环境文件不提交 |

## 前端

```text
frontend/
  src/
    main.tsx             浏览器入口
    vite-env.d.ts        Vite 类型
    app/                 App、导航、启动、providers 装配
    features/            业务页面、表单、模型及就近测试
    components/          跨业务共享 UI
    api/                 已授权 HTTP、Auth、DTO 和工作流通信
    shared/              纯契约、错误、时间和许可状态
    i18n/                词典、翻译与受注入端口控制的偏好上下文
    platform/            浏览器语音、音频和通知适配
    styles/              样式入口与保留原顺序的样式层
    test/                setup、synthetic fixtures、跨功能回归
  e2e/                   Playwright 端到端验收与 support 夹具
  public/                图标、manifest、通知服务工作线程
  tooling/               AST 依赖检查及其测试
```

详细文件表见 [src/README](../frontend/src/README.md)。
[features](../frontend/src/features/README.md) 分为 Assistant、会话、录入、药物、媒体、
今日用药、记录、照护、账户、提醒和引导。会话浏览独立归属，供账户和 Assistant 共用。

app 负责装配；业务 feature 使用声明的公开入口、API 和共享能力。
底层不反向引用 app/feature。禁止源码模块循环；跨 feature 的公开叶模块由
`frontend/architecture.config.mjs` 列出。不建立一次性导入所有页面的总导出桶。

`*.test.ts(x)` 是 Vitest 单元/组件测试；test/integration 是跨功能回归。
e2e 表示 end-to-end：Playwright 在真实浏览器点击完整流程；其 HTTP 可能是 mock 或本地后端，
不能因此声称验证过数据库/provider。各文件的环境和显式开关见 [e2e/README](../frontend/e2e/README.md)。

## 后端

| 层 | 内容 |
|---|---|
| `backend/app/contracts/` | 公开 DTO、Protocol、状态与工具契约 |
| `backend/app/domain/` | 纯安全、剂量、时间与库存规则 |
| `backend/app/application/` | 录入、报告、知识、照护、提醒和工作流用例 |
| `backend/app/agent/` | 有界编排、能力注册、allowlisted typed tools |
| `backend/app/infrastructure/` | 内存、SQL、Supabase、知识/视觉/语音/存储适配 |
| `backend/app/transport/` | 身份、HTTP、路由、患者与 worker composition roots |
| `backend/app/resources/` | 打包的版本化运行时资源 |

具体脚本见 [backend/app/README](../backend/app/README.md)。本次保持 Python 包路径和部署入口。
外部 Stage2 模型、权重与 owner 仓库不属于本项目改动范围。

## 脚本与运行

从仓库根运行 `python scripts/start_dev.py`，一个终端启动前后端。

| 位置 | 用途 |
|---|---|
| `scripts/start_dev.py` | 本地前后端启动和重载 |
| `scripts/run_patient_api.py` | Render 患者 API 资源检查与启动 |
| `scripts/run_reminders.py` | 独立 worker；不由开发启动自动执行 |
| `scripts/operations/` | 数据库、密钥等独立授权工具 |
| `scripts/qa/` | 离线评估、隔离目标检查及显式集成/发布验收 |
| `scripts/fixtures/` | synthetic/demo_only 素材生成 |
| `scripts/maintenance/` | 保守目录维护和本地文件索引 |

逐脚本副作用与运行要求见 [scripts/README](../scripts/README.md)。
不要把数据库变更、密钥生成和通知发送合并进默认开发启动。

## 工程检查与产物

在 frontend 运行 `npm run check:architecture`、`npm run typecheck`、`npm run lint`、
`npm run test` 和 `npm run build`；Playwright `--list` 只证明用例发现。
Python 与真实服务验收见 [开发指南](DEVELOPMENT.md) 和目标测试文件。

node_modules、dist、缓存和 outputs 是生成内容，不放业务源码。
私有计划、患者上传、运行证据及凭据不属于公开代码/部署物。
