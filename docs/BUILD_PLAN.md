# Executable Build Plan / 可打勾开发顺序

> Tick `[x]` only after **real code + actual tests/evidence**, not design, intent, screenshot mock or user conversation. For live team progress update `status/tasks.json` too. Generated on 2026-10-13 SGT.

## Timeboxes and release gates

| Date | Milestone | Exit gate |
|---|---|---|
| **10/13 (overnight + morning)** | Contracts/repo audit; backend, DB, synthetic minimal slice | manual enrollment → regimen → report dose; actual tests/logs |
| **10/14** | Stage2 adapter, Agent orchestration/safety, UI Smart Check | one normal+one reject branch, state persisted, model status accurately marked |
| **10/15** | Challenge 2 six features minimal closure; deployment; video/evidence | public browser demo, tests, chat screenshots, cover, GitHub |
| **10/16** | Freeze, confirm portal cutoff and submit | actual submission receipt; no risky new features |
| **11/03** | Possible Grand Final (if selected) | maintain deployment/trial validity |

## Team/owner labels

- **App**: backend/agent/repo/Data integration lead (assigned person TBD).
- **Vision**: existing Stage2 API/model owner (already debugging endpoints; do not duplicate).
- **UI**: React/PWA and interaction designer.
- **Infra**: Supabase/Auth/deployment/security.
- **QA**: independent test owner.
- **Submission/Media/Design**: competition package, video, diagrams, cover.
- A single person may cover several roles; the names must be filled during team stand-up, not guessed.

## Ordered task checklist

### Prep
- [x] **D001 · P0 · 2026-10-13 · Product** — 建立统一的详细项目需求 / Build canonical project docs. **Acceptance:** These docs and checklist exist and are packaged.
- [ ] **D002 · P0 · 2026-10-13 · App** — 合并文档至真实仓库并检查未覆盖旧文件 / Merge docs into the actual Git repository. **Acceptance:** git status shows copied docs and existing work preserved.
- [ ] **D003 · P0 · 2026-10-13 · App** — 核验真实仓库及当前文件状态 / Inspect actual repository and git remote. **Acceptance:** Record actual repo URL, branch and pre-existing files.
- [ ] **D004 · P0 · 2026-10-13 · App** — WorkBuddy 审查完整规格与 API / Run WorkBuddy Ask contract/architecture audit. **Acceptance:** Screenshot authentic WorkBuddy conversation, review and gaps.
- [ ] **D005 · P0 · 2026-10-13 · App** — 启动有约束的 WorkBuddy 夜间开发 / Run safe overnight Craft task. **Acceptance:** Local code/tests produced; work log has real results. **Depends:** D004.
- [ ] **D006 · P0 · 2026-10-13 · Submission** — 从开发一开始保留真实证据 / Keep development evidence from the outset. **Acceptance:** Evidence directory + first real screenshot saved.

### Backend
- [ ] **B001 · P0 · 2026-10-13 · App** — 初始化可维护的 FastAPI 分层后端 / Create FastAPI clean architecture project. **Acceptance:** Domain/application/adapter/transport separation and DI demonstrated. **Depends:** D002.
- [ ] **B002 · P0 · 2026-10-13 · App** — 建立 PostgreSQL Schema/迁移/RLS / Create PostgreSQL migrations, constraints and RLS. **Acceptance:** PK FK uniqueness check RLS and rollback tests. **Depends:** B001.
- [ ] **B003 · P0 · 2026-10-13 · App** — 独立匿名 Demo 用户与种子数据 / Add synthetic patient seed and demo auth isolation. **Acceptance:** Two demo users cannot view each other; reset idempotent. **Depends:** B002.
- [ ] **B004 · P0 · 2026-10-13 · App** — 建立源资料支持的手动药物草稿 / Implement source-backed manual medication draft. **Acceptance:** Missing regimen instructions stay pending. **Depends:** B002.
- [ ] **B005 · P0 · 2026-10-13 · App** — 实现带历史版本的 Regimen / Implement reviewed regimen versioning/history. **Acceptance:** New version retains old and rewrites future schedule only. **Depends:** B004.
- [ ] **B006 · P0 · 2026-10-13 · App** — Dose Schedule 与自述服药记录 / Implement dose schedule and self-report. **Acceptance:** Taken/not_taken/unsure and no-photo states persisted; duplicate writes blocked. **Depends:** B005.
- [ ] **B007 · P0 · 2026-10-13 · App** — 保存 Agent 会话状态与调用日志 / Add persistent Agent session and tool traces. **Acceptance:** Agent resumes tasks; tool calls and blocked actions auditable. **Depends:** B002.

### Vision
- [ ] **V001 · P0 · 2026-10-13 · Vision** — 提供 Stage2 最新真实请求响应与模型元数据 / Freeze latest PharmaScan API contract and provide real payloads.
  - **Acceptance:** real success/error responses for `/v1/model-info`, `/v1/detect`, `/v1/embed`, `/v1/match`, `/v1/identify`, `/v1/scan`, `/v1/read-label`; latest OpenAPI snapshot committed with version/provenance.
- [ ] **V002 · P0 · 2026-10-13 · Vision** — 调查单药两框 bug / Investigate one-pill double bounding-box regression. **Acceptance:** Single reference pill processed as at most one distinct pill; regression artifact.
- [ ] **V003 · P0 · 2026-10-14 · Vision** — 验证相似度阈值、歧义边际和拒识 / Calibrate threshold/margin/unknown detection. **Acceptance:** Validation split/metrics, no cosine-as-probability. **Depends:** V001.
- [ ] **V004 · P1 · 2026-10-14 · Vision** — 公开模型与 Embedding Space 版本 / Expose model/embedding-space version contract. **Status:** in_progress — do NOT tick done merely because `/model-info` is observed online; keep in_progress until a real response fixture is received and `model_version`, `embedding_space_id`, `dimension`, `normalization`, `preprocessing`, `threshold`/`margin` are verified. **Acceptance:** Versions and preprocessing contract verified by real response. **Depends:** V001.
- [ ] **V005 · P1 · 2026-10-14 · Vision** — 可选独立 Detection/Quality 工具 / Optional independent detection/quality API. **Acceptance:** One/multi-pill regression; measured flags, not invented. **Depends:** V002.

### Agent
- [ ] **A001 · P0 · 2026-10-14 · App** — 建立类型化 Tools、Adapters 与统一错误模型 / Implement typed tools and adapter contracts. **Acceptance:** Tool registry with no direct Agent ORM imports; contract tests. **Depends:** B001.
- [ ] **A002 · P0 · 2026-10-14 · App** — 实现独立确定性 Safety Gate / Implement deterministic safety/evidence policy. **Acceptance:** Reject wrong/current/missing source and cross-patient actions. **Depends:** B005.
- [ ] **A003 · P0 · 2026-10-14 · App** — 实现有状态多工具 Agent Loop / Implement stateful constrained Agent loop. **Acceptance:** At least 3 tasks use actual tools, clarification, persistence. **Depends:** A001,B007,A002.
- [ ] **A004 · P0 · 2026-10-14 · App** — 对接 Stage2 并处理 API 超时/契约失败 / Implement Stage2 adapter with timeout and mock isolation. **Acceptance:** Live status labeled; mock never reported as real success. **Depends:** A001,V001.
- [ ] **A005 · P0 · 2026-10-14 · App** — 实现个人图库版本兼容的 Match / Implement personal gallery reference matching. **Acceptance:** Patient scoped reference set, exact matching adapter, unknown result. **Depends:** A004,B005.
- [ ] **A006 · P0 · 2026-10-14 · App** — 实现 Unknown/Mismatch/Retake/Abstain / Implement unknown/mismatch retry/abstain branches. **Acceptance:** Clear cause only if measured; unresolved persistence. **Depends:** A003,A005.
- [ ] **A007 · P1 · 2026-10-14 · App** — 可选 Catalogue 初始视觉候选图库 / Optional catalogue-seeded candidate references. **Acceptance:** Different from verified personal refs; mapped market + licence check. **Depends:** A005.

### Frontend
- [ ] **F001 · P0 · 2026-10-14 · UI** — 完成 Mobile-first PWA 核心交互 / Implement portrait-first accessible patient PWA. **Acceptance:** 360px portrait + landscape + desktop responsive. **Depends:** B001.
- [ ] **F002 · P0 · 2026-10-14 · UI** — 实现独立 Demo 入口 / Add Try Demo and clean synthetic seed. **Acceptance:** New evaluator gets own data; no email needed; reset works. **Depends:** B003.
- [ ] **F003 · P0 · 2026-10-14 · UI** — 构建用药列表/手动登记页面 / Build medication list and manual enrollment. **Acceptance:** Show product vs regimen, pending fields, active/history. **Depends:** B005.
- [ ] **F004 · P0 · 2026-10-14 · UI** — 构建可选拍照的 Smart Check 和反馈 / Build Smart Check optional photo / intake status. **Acceptance:** Taken/Check/Not now/Unsure; not mandatory photo. **Depends:** B006,A005.
- [ ] **F005 · P1 · 2026-10-15 · UI** — 增加语音交互及文字后备 / Patient-friendly voice and text fallback. **Acceptance:** Speech failure fallback and mute option tested. **Depends:** F001.
- [ ] **F006 · P1 · 2026-10-15 · UI** — 构建历史/健康/预防/复诊页面 / Build history/health/prevention/review screens. **Acceptance:** 6 challenge capabilities accessible in UI. **Depends:** L003.

### Features
- [ ] **OCR01 · P1 · 2026-10-14 · App** — 集成 PharmaScan 标签/包装提取与疗程字段核对 / Integrate PharmaScan label/package extraction and regimen field review. **Status:** in_progress.
  - **Acceptance:** readable box/pharmacy-label image uses `/v1/read-label`; provider response normalized into the app DTO; source image/provenance preserved; product identity and patient regimen kept separate; missing dose/frequency/time/duration remain null; patient reviews regimen-relevant source fields; manual enrollment remains available.
  - **Depends:** B004.
- [ ] **OCR02 · P1 · 2026-10-14 · Vision + App** — 验证药房标签疗程指示提取 / Validate pharmacy-label regimen instruction extraction.
  - **Acceptance:** test representative synthetic/Singapore-style pharmacy labels for medicine name, ingredient, strength, dosage form, dose quantity, frequency, administration time, food instruction, PRN, duration when explicitly present, and special instruction. Each extracted field must distinguish **present / missing / ambiguous**. Missing fields must not be inferred.
- [ ] **K001 · P1 · 2026-10-14 · App** — 建立有来源的药物解释 Tool / Add source-backed medication education. **Acceptance:** Patient language info with source; personal dose from regimen. **Depends:** A001.
- [ ] **K002 · P1 · 2026-10-15 · App** — 带覆盖率的潜在 DDI/重复成分提示 / Advisory DDI/duplicate screening with coverage. **Acceptance:** No-alert does not imply safe; NC licence disclosure. **Depends:** B005.
- [ ] **L001 · P1 · 2026-10-15 · App** — 记录血压血糖症状与时间趋势 / Track dated health observations and trends. **Acceptance:** Units/date/source; no causal diagnosis. **Depends:** B002.
- [ ] **L002 · P1 · 2026-10-15 · App** — 实现预防筛查/随访/生活方式任务 / Implement preventive health/care tasks. **Acceptance:** User/source-backed tasks beyond refill. **Depends:** B002.
- [ ] **L003 · P1 · 2026-10-15 · App** — 生成复诊准备摘要与讨论问题 / Generate patient-reviewable healthcare prep report. **Acceptance:** Factual meds, adherence unknowns, observations, questions. **Depends:** L001,L002.
- [ ] **L004 · P2 · 2026-10-15 · App** — 实现授权照护者有限通知 / Add verified consent-limited caregiver notifications. **Acceptance:** No actual send until verified; no clinical interpretation. **Depends:** B002.

### Quality
- [ ] **T001 · P0 · 2026-10-14 · QA** — 验证身份及跨用户隔离 / Run auth and cross-patient isolation tests. **Acceptance:** JWT access rejection and RLS isolation pass. **Depends:** B003.
- [ ] **T002 · P0 · 2026-10-14 · QA** — 执行视觉失败与用药安全负例测试 / Run vision/agent safety negative tests. **Acceptance:** No high similarity as identity; one-pill 2-box caught. **Depends:** A006.
- [ ] **T003 · P0 · 2026-10-14 · QA** — 代码质量、类型检查、迁移测试 / Run Python/TS lint/type/tests and migrations. **Acceptance:** Actual outputs and failures recorded; no invented pass. **Depends:** B001,F001.
- [ ] **T004 · P0 · 2026-10-15 · QA** — 执行多日真实工具轨迹演示 / Perform multi-day connected demo with tool trace. **Acceptance:** Enrollment, normal check, abstain, long-term summary. **Depends:** A003,L003.
- [ ] **T005 · P1 · 2026-10-15 · QA** — 手机竖屏横屏与辅助功能测试 / Usability/UX phone and landscape checks. **Acceptance:** No clipped buttons, large font, speech fallback. **Depends:** F006.

### Deploy
- [ ] **DEP01 · P0 · 2026-10-15 · Infra** — 创建 Supabase 项目并启用安全访问 / Set up Supabase Auth/DB/Storage/RLS environment. **Acceptance:** No secrets committed; migration run; two demo users isolated. **Depends:** B002.
- [ ] **DEP02 · P0 · 2026-10-15 · Infra** — 部署 FastAPI 并验证健康检查 / Deploy backend with health/error tests. **Acceptance:** Public HTTPS API health correct, actual tool credentials safe. **Depends:** DEP01,A003.
- [ ] **DEP03 · P0 · 2026-10-15 · Infra** — 部署 PWA 前端和真实浏览器测试 / Deploy frontend and browser incognito check. **Acceptance:** Accessible URL mobile/desktop; Try Demo works. **Depends:** DEP02,F006.

### Submit
- [ ] **S001 · P0 · 2026-10-15 · Submission** — 确认实际提交截止时刻和字段 / Confirm official portal requirements and cutoff time. **Acceptance:** Form screenshot/verified hard required vs optional.
- [ ] **S002 · P0 · 2026-10-15 · Submission** — 确定项目标题与少于10词简介 / Approve title and <10-word blurb. **Acceptance:** Human approval, count verified.
- [ ] **S003 · P0 · 2026-10-15 · Submission** — 完善四块 Project Description / Write final four-part project description. **Acceptance:** Claims link to actual code/tests and impact definition. **Depends:** T004.
- [ ] **S004 · P0 · 2026-10-15 · Design** — 设计 16:9 封面图 / Create 16:9 cover image. **Acceptance:** 380x216 recommended, verified dimensions/link.
- [ ] **S005 · P0 · 2026-10-15 · Submission** — 保存至少3张真实 WorkBuddy 聊天截图 / Capture three real WorkBuddy chat screenshots. **Acceptance:** Real UI history + code and debug evidence. **Depends:** D005.
- [ ] **S006 · P0 · 2026-10-15 · Submission** — 提交真实源码 GitHub URL / Link actual GitHub source repository. **Acceptance:** Accessible URL, licenses, no secret leaks. **Depends:** T003.
- [ ] **S007 · P1 · 2026-10-15 · Media** — 录制 5–8 分钟演示视频 / Record 5–8-minute honest demo video. **Acceptance:** Actual prototype, includes tools and build reflection. **Depends:** T004.
- [ ] **S008 · P1 · 2026-10-15 · Design** — 制作架构与信任边界 PPT / Create architecture/trust-boundary PPT. **Acceptance:** Show boundaries, agent/tools and proposed vs working. **Depends:** A003.
- [ ] **S009 · P0 · 2026-10-16 · Submission** — 完成正式提交 / Submit app URL, fields and proof to portal. **Acceptance:** Submission receipt screenshot and working links. **Depends:** S001,S003,S004,S005,S006.
- [ ] **S010 · P2 · 2026-10-16 · Marketing** — 可选社交媒体发布加分 / Optional social media post with required hashtags. **Acceptance:** Authentic post link and hashtags with no fake claims.
- [ ] **S011 · P1 · 2026-10-16 · Submission** — 最终部署测试与冻结 / Final production smoke test and submission freeze. **Acceptance:** Incognito onboarding, tests, evidence, receipt archived. **Depends:** DEP03,S009.

### Future
- [ ] **R001 · P2 · after-10-16 · Vision** — 后续包装图与无字药板模型实验 / Evaluate new blister/package image models. **Acceptance:** Separate dataset and modality validation.
- [ ] **R002 · P2 · after-10-16 · Vision** — 后续双头/持续训练研究 / Explore dual-head model and periodic retraining. **Acceptance:** Versioned model evaluation, consent and ground truth.
- [ ] **R003 · P2 · after-10-16 · Product** — 后续 HSA/临床/市场与医疗系统对接 / Clinical/HSA/market validation and hospital integration. **Acceptance:** Formal legal/clinical assessments and licenses.

## Done / Blocked protocol

For each completed task, update `status/tasks.json` status/evidence/updated_at and `status/WORK_LOG.md` with real tests. A task is **blocked** only when its dependency (secret, cloud grant, real Stage2 response, legal permission) cannot be satisfied; continue independent tasks and record in `status/BLOCKERS.md`. No human approval → no paid resources, cloud production mutation or repository push.

**Initial completed documentation tasks: 1 of 61; implementation completion unverified.**