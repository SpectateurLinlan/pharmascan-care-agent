# 前端源码地图

根目录只保留 `main.tsx`（浏览器启动）和 `vite-env.d.ts`（构建环境类型）。
页面按业务归属放进 features；不再把所有页面和控件混放进 components。

| 目录 | 内容与入口 |
|---|---|
| [app/](app/README.md) | App、导航、启动与 provider 装配 |
| [features/](features/README.md) | Assistant、会话、录入、药物、证据、今日用药、记录、照护、账户、提醒和引导 |
| [components/](components/README.md) | Icon、BottomSheet、布局、反馈、语言/语音输入等共享 UI |
| [api/](api/README.md) | 已授权 HTTP、Auth SDK、工作流通信和开发诊断 |
| [shared/](shared/README.md) | 纯 DTO、错误、路由、日期时间与图片许可 |
| [i18n/](i18n/README.md) | 翻译、词典及由 app 注入持久化的偏好上下文 |
| [platform/](platform/README.md) | 浏览器语音、音频、通知和服务工作线程适配 |
| [styles/](styles/README.md) | index.css 入口、tokens、base、共享和患者页面样式 |
| [test/](test/README.md) | Vitest setup、synthetic fixtures 与跨功能回归 |

app 负责装配；feature 使用公开业务入口、API 与共享能力。底层不反向依赖 app/feature。
业务模块之间允许通过声明的叶模块协作；不允许源码模块循环或跨模块私有导入。
检查：`npm run check:architecture`。该检查同时解析静态、动态和 type-only 导入。

单元/组件测试使用同目录 `*.test.ts(x)`；跨模块回归放 test/integration。
浏览器端到端验收位于 [../e2e/](../e2e/README.md)，不是生产功能代码。

注释简短说明责任、输入/输出或边界原因。公开导出保持 typed props/DTO；不新增隐藏客户端。
