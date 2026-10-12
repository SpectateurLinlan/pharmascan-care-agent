# WorkBuddy Overnight / Development Guide — actionable, safe and evidence-producing

## 1. Pre-flight before bed (5–15 min)

1. Repo root: `D:\Projects\pharmascan-care-agent` already reportedly exists. **Compare before copying** `PROJECT_BRIEF.md`; merge this package's enhanced version; keep other developer commits and Stage2 repo unchanged. Check `git status`, `git remote -v`; avoid overwrite.
2. Place `00_START_HERE.md`, `AGENTS.md`, `CODEBUDDY.md`, `.codebuddy/rules/engineering/RULE.mdc`, `PROJECT_BRIEF.md`, `docs/*`, `prompts/*`, `status/*`, `tests/*` at repository root. The old interactive HTML/WORKFLOW_SPEC preserved in `docs/reference/` only; the Stage2 owner may already be using that contract.
3. Open WorkBuddy with the project directory (not whole D:). Select model with good multi-file coding/reasoning if available; code quality depends on constraints, tests and repo context more than any model name.
4. Check permissions **Default Permissions**; allow file edits/ordinary tests within project, avoid Full Access and third-party secrets; don't enable any payments, production modifications, remote account creation or automatic external publishing.
5. Have a browser for HF Stage2 `/docs` and existing teammate's real endpoint responses if available, but no need to clone/train Stage2 for main app. Prepare `.env.example`, not actual `.env` in chat/GitHub.
6. Open one initial WorkBuddy **Ask** message from `prompts/01_RECON_AND_CONTRACT_ASK.md` (if team repo never audited); save a real screenshot. To run overnight without being stopped at Plan's approval gate, proceed to **Craft** using `prompts/02_OVERNIGHT_BUILD_CRAFT.md` with explicit safety authorization. WorkBuddy may still require host approval; user should approve safe repository actions before leaving, never weaken access broadly.

## 2. WorkBuddy versus CodeBuddy rule loading — verified scope and fallback

**CodeBuddy IDE** officially supports repository-level `CODEBUDDY.md`, fallback `AGENTS.md`, and `.codebuddy/rules/*/RULE.mdc` with `alwaysApply: true` project rules. The official guide states a new chat may be required after rule changes, and references must be loaded at new session start: https://www.workbuddy.cn/docs/ide/User-guide/Rules . This **does not prove the standalone WorkBuddy desktop app loads these files automatically**. Its Enterprise custom-instruction feature may be account-dependent, so do not promise one universal settings toggle.

**Reliable method in WorkBuddy:** every task prompt MUST explicitly say: “先读取项目根目录 `AGENTS.md`、`PROJECT_BRIEF.md` 及相关 docs；先回复架构约束和安全边界摘要，再工作；改动后运行测试并写 `status/WORK_LOG.md`。” Keep core `AGENTS.md` short enough to be reread, link to full spec rather than pasting 144-page history every time. If WorkBuddy has selectable project skills/rules in your installed version, add equivalent instructions there, but verify they really load by asking it which instructions it used.

## 3. Mode sequence and spending focus

| Phase | Mode | When | Input file/prompt | Expected durable output |
|---|---|---|---|---|
| 0 · Audit | **Ask** | once, short | `01_RECON_AND_CONTRACT_ASK.md` | repo truth + model API gaps; screenshot #1 |
| 1 · Architecture acceptance | **Plan** (supervised only) | if you can approve now | full docs + task dependencies | architecture decision record, public ports, approved vertical slice |
| 2 · Overnight build | **Craft** (single scoped assignment) | before sleeping | `02_OVERNIGHT_BUILD_CRAFT.md` | minimal backend+DB/test+Agent slice with honest fallbacks |
| 3 · Integration | **Craft**, after morning review | 10/13–14 | `03_MORNING_INTEGRATION.md` | Stage2 adapter/agent real tool traces + patient PWA; screenshots #2–3 |
| 4 · Release QA | **Craft**, supervised | 10/15 | `04_FINAL_RELEASE_QA.md` | test matrix, screenshot evidence list, README, demo freeze |

**Do not start seven parallel WorkBuddy autonomous tasks writing the same repository.** Use one stable workspace, scoped sequential stages and Git commits. Invest most model credits in tool integration, stateful Agent, error handling and tests, not repeating past commercial debates. Assign UI work only after base API/schema is stable.

## 4. Unattended / no-answer policy

- May proceed autonomously with reversible repository-local code/fixtures/tests/docs and local unprivileged commands.
- Before any block, write `status/BLOCKERS.md`, choose a safe deterministic stub/mock **labelled SIMULATED**, keep other independent tasks moving.
- Never invent actual token/secrets, never clone an unreviewed repo to infer provider contracts, never upload patient images as training labels, never provision paid cloud, never deploy automatically or `git push --force`.
- If local database/cloud endpoint unavailable, write migrations and repositories and run mocked unit/integration tests; report what was truly run. If actual Stage2 response unavailable, create a documented adapter + golden-fixture test placeholders, mark live integration blocked.
- Set checkpoints: inspect repo/constraints → implement minimal vertical slice → test → update work log → commit locally if allowed → next P0 task. If program stops, restart from log rather than duplicating code.
- No blind 'comprehensive system' generated in one huge monolith; add incremental tests and clean diff.

## 5. Evidence: what and when to screenshot

1. **Requirements and design**: WorkBuddy reads `AGENTS.md`, structured requirements and actual repo files; identifies Stage2 vs app boundary and selected vertical slice. Screenshot must show actual WorkBuddy conversation and its analysis, not an edited presentation slide.
2. **Agent tool integration**: WorkBuddy shows actual code changes to typed tool registry, mediator and policy gate; ideally includes a tool trace from a real test.
3. **Bug fixing and validation**: the failing TEVA single-pill double box / version mismatch / duplicate dose event test and WorkBuddy's actual fix, then passing tests. Keep terminal logs and commit hash, not a fake before/after.
4. Optional screenshots: OCR adapter validation, Supabase tenant isolation tests, speech fallback, final QA. In report, separately attribute Stage2 model owner vs WorkBuddy assisted work.

## 6. What to hand WorkBuddy each session

- Send `PROJECT_BRIEF.md` **plus** `docs/MASTER_SPEC.md`, `docs/WORKFLOWS.md`, `docs/API_CONTRACTS.md` and `AGENTS.md` as the relevant long-lived project context. The earlier `PROJECT_BRIEF.md` was too sparse; replace/upgrade it but keep a short entry/index rather than pasting all content into it.
- The 144-page compiled PDF is *historical discussions / source audit*, not a replacement for operational requirements or official Hackathon PDF. WorkBuddy should work from curated canonical docs and original docs in reference only when resolving conflicts.
- Staged prompts below in `/prompts`. Do not ask WorkBuddy to rediscover B2C vs B2B2C, model training or regulatory scheme unless new evidence appears.

## 7. When WorkBuddy asks a question during unattended work

It should: determine whether question is genuinely blocking, apply canonical decision from docs, proceed if reversible, and record assumption. For credentials, licenses, external deployment, irreversible DB migration, privacy risk or clinically meaningful scope change: **stop that subtask**, not the entire local repository build. Leave a readable blocker/next-action note. User decides in the morning.
