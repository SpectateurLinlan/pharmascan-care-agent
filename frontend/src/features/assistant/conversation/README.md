# Assistant conversation

聊天、回答依据及应用工作流交互；通过各业务公开表单推进操作。

| 文件 | 职责 |
|---|---|
| [AnswerSources.tsx](AnswerSources.tsx) | 来源及查询依据展示 |
| [AssistantScreen.tsx](AssistantScreen.tsx) | 聊天、语音、来源和任务进度的交互装配 |
| [MedicationChoices.tsx](MedicationChoices.tsx) | 同名/相似名候选和已有药物的显式选择 |

同目录 `*.test.ts(x)` 为 synthetic 本地回归；表单提交继续使用既有独立确认。
