# 浏览器能力与外部适配

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [authDiagnostic.spec.ts](authDiagnostic.spec.ts) | 身份诊断、刷新和失败状态 | 见文件头和测试数据装配；不自动启用真实服务 |
| [browserTts.spec.ts](browserTts.spec.ts) | 浏览器原生语音能力和适配器生命周期 | 见文件头和测试数据装配；不自动启用真实服务 |
| [performanceLocal.spec.ts](performanceLocal.spec.ts) | 中英文启动输入框、慢会话／资料、偏好响应与首屏测量 | 输入框用 loopback 拦截 DEMO；其他场景需 `RUN_ASSISTANT_STARTUP`、`RUN_PERFORMANCE_LOCAL` |
| [stage2Compatibility.spec.ts](stage2Compatibility.spec.ts) | Stage2 0.10.0 兼容演示；与图库演示的参数/入口不同 | `RUN_STAGE2_V010_DEMOS` |
| [webPushLocal.spec.ts](webPushLocal.spec.ts) | 通知设置与本地服务工作线程 | `RUN_PUSH_LOCAL` |

启动输入框场景不连接后端，所有 API 均由本地 DEMO 拦截。启动 Vite 时需禁用本地
Supabase 配置；Windows PowerShell 可将 `VITE_SUPABASE_URL` 和
`VITE_SUPABASE_PUBLISHABLE_KEY` 设为单个空格（认证装配会 trim 为空），避免空字符串
被系统移除后重新读入 `.env.local`。测试会拒绝外部请求，不会创建云端访客账号。
