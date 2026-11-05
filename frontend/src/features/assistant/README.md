# assistant

聊天、回答依据及应用工作流交互；通过各业务公开表单推进操作。

- [conversation/](conversation/README.md)：聊天主界面、药物选择和回答依据
- [model/](model/README.md)：工作流状态和回答展示的纯模型
- [workflow/](workflow/README.md)：各类应用能力的办理交互



`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
