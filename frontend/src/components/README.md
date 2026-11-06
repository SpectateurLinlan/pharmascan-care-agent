# 共享组件

跨业务 UI；只依赖 i18n、platform 与 shared，不依赖请求客户端或业务页面。

| 文件 | 职责 |
|---|---|
| [BottomSheet.tsx](BottomSheet.tsx) | 底部复核层、焦点和关闭行为 |
| [feedback.tsx](feedback.tsx) | 错误/成功反馈；只依赖纯错误契约 |
| [Icon.tsx](Icon.tsx) | 共享 SVG 图标和 IconName 类型 |
| [LanguageMenu.tsx](LanguageMenu.tsx) | 语言选择交互 |
| [layout.tsx](layout.tsx) | Screen/Row/Callout 等共享布局和状态展示 |
| [NotBuiltYetScreen.tsx](NotBuiltYetScreen.tsx) | 尚未提供能力的明确展示 |
| [primitives.tsx](primitives.tsx) | Card/Tag/模拟说明等共享表面；兼容反馈导出 |
| [TextSizeSlider.tsx](TextSizeSlider.tsx) | 字号预览与通过偏好端口保存 |
| [VoiceInput.tsx](VoiceInput.tsx) | 语音状态及可编辑转录输入 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。

`DeferredScreen.tsx`：跨页面及聊天办理面板的独立加载、失败重试边界；加载时保留外围界面。
