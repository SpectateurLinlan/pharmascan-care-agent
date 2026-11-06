# 应用装配

应用根、providers、导航与启动分区；业务 feature 不反向导入这里。

| 文件 | 职责 |
|---|---|
| [App.tsx](App.tsx) | 应用外壳、各业务入口与页面装配；保留延迟加载 |
| [bootstrap.ts](bootstrap.ts) | 不依赖 React／认证的轻量启动、应用下载失败重试与输入法交接 |
| [mountApplication.tsx](mountApplication.tsx) | 延迟加载 React、完整样式与应用；开发诊断仍仅在原允许地址启用 |
| [startupDraft.ts](startupDraft.ts) | 当前页面内存中的一次性输入交接 DTO；切换身份后清除 |
| [AssistantEntry.tsx](AssistantEntry.tsx) | 连接前可输入的本地聊天入口；核对身份与会话后交接文字，不自动发送 |
| [DeferredScreen.tsx](DeferredScreen.tsx) | 页面独立加载/错误边界与重试 |
| [greeting.ts](greeting.ts) | 时段问候和显示名称格式 |
| [LanguageProvider.tsx](LanguageProvider.tsx) | 在应用装配点注入已授权偏好 API |
| [useCareNavigation.ts](useCareNavigation.ts) | 浏览器导航 Hook、返回栈和离开确认 |
| [StartupSection.tsx](StartupSection.tsx) | 启动时的分区状态展示 |
| [startupState.ts](startupState.ts) | 首页分区就绪与空状态的纯判断 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。

启动时健康检查、偏好、用药列表和历史读取并行进行；临床资料仍需通过身份与协议检查。
聊天入口独立显示，连接前文字仅在页面内存中保留，发送按钮禁用；同一用户会话就绪后
交接文字、焦点及光标，不自动发送，输入法组合输入结束后再交接。切换账户会清空旧页面状态。

`DeferredScreen.tsx` 保留兼容导出，实现位于 `components/DeferredScreen.tsx`，业务界面直接使用共享组件。药物、库存和聊天办理表单按需加载；聊天输入框不依赖这些下载。历史用药页首次打开后保持挂载，保留筛选状态。

连接前的图片／语音按钮使用禁用状态，与正式输入框保持相同布局；只有文字在本地可编辑。自动恢复已有对话时继续保留可编辑文字，发送等待恢复结束；明确切换对话和实际提交的保护保持不变。
