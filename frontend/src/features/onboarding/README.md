# onboarding

首次使用引导及按用户保存的进度。

| 文件 | 职责 |
|---|---|
| [onboarding.ts](onboarding.ts) | 按用户保存引导进度与终止状态 |
| [OnboardingGuide.tsx](OnboardingGuide.tsx) | 首次使用引导、重放和焦点控制 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
