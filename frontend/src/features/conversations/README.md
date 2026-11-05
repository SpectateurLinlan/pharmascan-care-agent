# conversations

账户和 Assistant 共用的会话浏览；独立归属以避免账户反向依赖 Assistant。

| 文件 | 职责 |
|---|---|
| [conversationDates.ts](conversationDates.ts) | 会话日期分组与标签 |
| [ConversationHistory.tsx](ConversationHistory.tsx) | 历史会话偏好与已保存对话入口 |
| [ConversationHistoryBrowser.tsx](ConversationHistoryBrowser.tsx) | 会话列表、分页及切换 |
| [ConversationSurface.tsx](ConversationSurface.tsx) | 共享聊天消息表面和定位交互 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
