# Assistant model

聊天、回答依据及应用工作流交互；通过各业务公开表单推进操作。

| 文件 | 职责 |
|---|---|
| [assistantResponsePresentation.ts](assistantResponsePresentation.ts) | 将工具轨迹转为用户可理解的回答依据 |
| [assistantWorkflowActions.ts](assistantWorkflowActions.ts) | 工作流输入/选择事件的纯构造 |
| [assistantWorkflowState.ts](assistantWorkflowState.ts) | 当前任务、草稿和待处理原图的内存状态 |

同目录 `*.test.ts(x)` 为 synthetic 本地回归；表单提交继续使用既有独立确认。
