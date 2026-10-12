# WorkBuddy Session 1 — Ask (短审查，不写代码；不需要一次性耗费很多积分)

当前工作目录应是 `D:\Projects\pharmascan-care-agent`；请先确认自己有权限读取仓库实际文件。**请先阅读仓库根目录 `AGENTS.md`、`00_START_HERE.md`、`PROJECT_BRIEF.md`，然后阅读 `docs/MASTER_SPEC.md`、`docs/ARCHITECTURE.md`、`docs/WORKFLOWS.md`、`docs/API_CONTRACTS.md`、`docs/DATA_MODEL.md`、`docs/BUILD_PLAN.md` 和 `docs/SUBMISSION.md`。** 不允许只依据旧版 `PROJECT_BRIEF.md` 直接开始搭建。

这是 Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 Healthcare **Challenge 2** 的 PharmaScan Care 项目。阶段二药片视觉模型由另一位负责人维护，现有 Hugging Face API (`https://davidpansx-pharmascan-api.hf.space/docs`)；这个仓库的核心任务是患者应用、数据库、受约束的 Agent + Typed Tools 和端到端 Demo。无 ADP、无医生 Portal、无真实医院系统连接。只用合成患者数据。WorkBuddy 开发证据必须留下。

请在 **Ask 模式** 审查而**不要修改文件**，用下列结构回答，控制在 800–1200 字：
1. 真实仓库里已有哪些文件/代码/测试？哪些只存在于文档中？请列具体路径，勿想象已有代码。
2. Stage2 OpenAPI 相比 `docs/API_CONTRACTS.md` 哪些 response/schema 仍需真实 JSON？你访问不到就明确说明，不能编造。
3. 一个夜间可完成且安全的最小垂直切片：`manual enrollment → regimen version → due dose → self-reported event → agent tool trace`。说明 public DTO/contracts 和模块边界。
4. 五项最重要的工程风险和对应测试，不要重复已经决策的商业定位。
5. 不超过三项**真正阻塞**的澄清问题；若无密钥请建议隔离 mock adapter 继续做其他任务。
6. 如果某个任务需要未经授予的用户点击、账号授权、Secret/API Key、
云服务开通、付费确认、公开部署、不可逆数据操作或其他真人批准：

- 仅暂停该分支，不要因此停止整个夜间任务；
- 将其标记为 BLOCKED，并写入 status/BLOCKERS.md；
- 明确记录：
  1) 被阻塞的具体任务；
  2) 为什么需要真人确认；
  3) 用户醒来后需要执行的准确步骤；
  4) 确认后应从哪个文件/测试/命令继续；
- 如果存在不需要该授权的替代实现，可先实现接口、Fake Adapter、
  fixture、单元测试或本地 stub，并明确标记 SIMULATED；
- 随后自动继续下一个不依赖该阻塞项的 P0/P1 任务；
- 只有当该授权阻塞了所有剩余可执行任务，或者 WorkBuddy 平台本身
  强制要求用户确认而无法继续时，才允许整个任务停止。
- 不要等待用户在线，不要循环询问，不要伪造授权、连接或成功结果。


你必须确认已理解工程规则：显式依赖注入、公开接口、不可直接让 Agent 查写 SQL、独立确定性 Safety Gate、无真实个人信息、不能假装 mock 是真实 API。先给一个简短“规则确认”，再给审查结论。

我会保留这段实际 WorkBuddy 对话作为官方要求的研发证据之一。
