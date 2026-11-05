# 浏览器能力与外部适配

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [authDiagnostic.spec.ts](authDiagnostic.spec.ts) | 身份诊断、刷新和失败状态 | 见文件头和测试数据装配；不自动启用真实服务 |
| [browserTts.spec.ts](browserTts.spec.ts) | 浏览器原生语音能力和适配器生命周期 | 见文件头和测试数据装配；不自动启用真实服务 |
| [performanceLocal.spec.ts](performanceLocal.spec.ts) | 偏好慢响应、启动缓存和首屏测量 | `RUN_ASSISTANT_STARTUP`、`RUN_PERFORMANCE_LOCAL` |
| [stage2Compatibility.spec.ts](stage2Compatibility.spec.ts) | Stage2 0.10.0 兼容演示；与图库演示的参数/入口不同 | `RUN_STAGE2_V010_DEMOS` |
| [webPushLocal.spec.ts](webPushLocal.spec.ts) | 通知设置与本地服务工作线程 | `RUN_PUSH_LOCAL` |
