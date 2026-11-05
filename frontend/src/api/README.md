# 后端接口

前端业务 HTTP 的统一边界。Auth SDK 仅用于身份；接口代码不得导入 UI/feature。

| 文件 | 职责 |
|---|---|
| [abortable.ts](abortable.ts) | 可取消请求辅助 |
| [assistantWorkflows.ts](assistantWorkflows.ts) | typed 工作流请求/响应与后台运行状态 |
| [assistantWorkflowStream.ts](assistantWorkflowStream.ts) | 工作流事件流接收、取消与失败处理 |
| [auth.ts](auth.ts) | 仅 Supabase 身份 SDK；不读写患者业务表 |
| [care.ts](care.ts) | 照护、库存、困难和跟进 DTO |
| [client.ts](client.ts) | 已授权后端 API 门面、请求共享及现有响应契约 |
| [diagnosticContract.ts](diagnosticContract.ts) | 只含脱敏技术事件的诊断契约 |
| [dose.ts](dose.ts) | 剂量来源与展示 DTO |
| [doseFollowUps.ts](doseFollowUps.ts) | 受限历史报告和审核 DTO |
| [localDiagnostics.ts](localDiagnostics.ts) | 本机开发环境的只读 Auth/数据访问诊断 |
| [workflowDiagnostics.ts](workflowDiagnostics.ts) | 本机工作流诊断安装与移除 |
| [workflowPerformanceContract.ts](workflowPerformanceContract.ts) | 工作流时序和请求指标的脱敏契约 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
