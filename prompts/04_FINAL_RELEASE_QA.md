# WorkBuddy Session 4 — Release QA and Submission Freeze (10/15–16)

先读取 `AGENTS.md`、`docs/SUBMISSION.md`、`docs/SAFETY_AND_EVALUATION.md`、`docs/BUILD_PLAN.md` 和真实运行代码/日志；**禁止添加新大型功能**。目标是让比赛材料“可运行、可验证、诚实”。

1. 用实际代码执行 Python Ruff/Pytest、TypeScript typecheck/ESLint/build、PostgreSQL migration/rollback（有本地环境时）、Agent/tool integration、安全和用户隔离；列实际测试命令/失败/修复/结果，不编造数值。
2. 验证端到端 Demo：`Try Demo → medication enrollment → optional gallery/real or labelled-simulated Stage2 → routine dose self-report → uncertainty/abstention → multi-day review`, 六项 Challenge 2 的每项最小 UI/工具证据。External unavailable 可作为明确降级，不准偷换成假成功。
3. 重点查：一个 pill 双重检测、相似度 0.99 错配、模型版本冲突、stopped medication、missing dose instructions、user unsure、重复 Taken、cross-patient read、caregiver consent、API timeout、无字 blister。
4. 检查 README、公开 API contracts、repo tree、setup docs、`.env.example` 与 secret scanner、Git licence notices；全部旧/未实现接口必须明确区分。
5. `docs/SUBMISSION.md` 完成 project title、少于10词 Short Blurb、四部分 Description、cover placeholder 状态、public link placeholder 或真实 URL、5–8 min Demo Video outline/link、真实 WorkBuddy history 与≥3 screenshots、source GitHub link、architecture PPT guide、optional social link。
6. 写 `status/FINAL_QA.md` 状态表：IMPLEMENTED / PARTIAL / SIMULATED / NOT BUILT；真实 test counts、未解决问题、可复现运行命令、哪些展示场景已经能打开 URL；不要声称正式 HSA 审批或临床效益。
7. 不能自行创建公开可访问部署/发布社交媒体/提交比赛表单，除非人类明确授权。即使用户不在电脑前，也必须在该边界暂停并输出待办。

完成后给我一个可读的 release gate verdict 和最少应采取的人工步骤，留下源码、测试日志、WorkBuddy 真实会话和文件变更供截图。
