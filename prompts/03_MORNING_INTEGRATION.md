# WorkBuddy Session 3 — Craft (10/13–10/14; after reviewing overnight outputs)

请先读 `AGENTS.md`、`PROJECT_BRIEF.md`、`docs/API_CONTRACTS.md`、`docs/WORKFLOWS.md`、`docs/SAFETY_AND_EVALUATION.md`、`status/WORK_LOG.md`、`status/BLOCKERS.md` 和项目真实代码及 tests。检查 overnight commit/diffs 和测试输出，不相信“完成了”但没有证据的任务。

**任务按顺序：**
1. 用 Stage2 负责人提供的**最新真实** `/embed`,`/match`,`/identify`,`/scan` 请求及响应 JSON 更新 Adapter/DTO + contract tests。若还未提供，继续隔离 Mock，不要编造字段。确保 API timeout/similarity/embedding version/unknown 高相似度场景处理。
2. 把 **Personal Gallery** 的 `catalogue_seeded_candidate`、`patient_loose_pill`、`package` 严格分开。只在 encoder 兼容时比较 embeddings；不假设 `/v1/pills/{id}/embeddings` 已存在。创建当前 vs 历史用药的 reference eligibility 逻辑。
3. 做 OCR + source review 版本化计划最小闭环；若依赖无法安装，保持手动表单作为稳定路径。
4. 加入真实 LLM Tool Calling（仅在已通过安全授权并有 Server-side Key 时），执行真正的 Agent tool calls / user clarifications / persistent event; 若无 Key，保留 deterministic-demo 并明示；**绝不将 fallback 冒充真实 agent**。
5. 实现 Patient PWA `Try Demo → Medication List → Add → Smart Check (optional) → History → Health/Tasks → Review`，手机 Portrait 优先，Landscape/desktop 响应式；任何未接后端功能不要展示成功状态。
6. 运行最少六个集成场景：正常；错药；模糊/重复box；历史停药；忘记吃药；缺失服药指示。记录 tool traces 和 contract test output。

**输出要求：** 改动文件、接口/API、真实/模拟功能、实际测试输出、权责检查、待解决安全问题、真实 WorkBuddy 截图建议 2/3。只修改拥有的组件，经验证后才更新 `status/tasks.json` 与 `status/WORK_LOG.md`。不得推送、收费或上线前不请求人类确认。
