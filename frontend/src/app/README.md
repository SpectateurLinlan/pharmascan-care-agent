# 应用装配

应用根、providers、导航与启动分区；业务 feature 不反向导入这里。

| 文件 | 职责 |
|---|---|
| [App.tsx](App.tsx) | 应用外壳、各业务入口与页面装配；保留延迟加载 |
| [DeferredScreen.tsx](DeferredScreen.tsx) | 页面独立加载/错误边界与重试 |
| [greeting.ts](greeting.ts) | 时段问候和显示名称格式 |
| [LanguageProvider.tsx](LanguageProvider.tsx) | 在应用装配点注入已授权偏好 API |
| [useCareNavigation.ts](useCareNavigation.ts) | 浏览器导航 Hook、返回栈和离开确认 |
| [StartupSection.tsx](StartupSection.tsx) | 启动时的分区状态展示 |
| [startupState.ts](startupState.ts) | 首页分区就绪与空状态的纯判断 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
