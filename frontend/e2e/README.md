# 浏览器端到端测试（e2e）

e2e 是 **end-to-end**：用 Playwright 打开真实浏览器，点击页面并检查一段完整流程。
它与 src 下的 Vitest 单元/组件测试不同，不会被 `npm run test` 自动执行。
这里也包含 HTTP mock 的浏览器测试：有浏览器不等于验证了真实后端/数据库/外部服务。

| 子目录 | 测试范围 |
|---|---|
| [assistant/](assistant/README.md) | Assistant 对话与工作流 |
| [medications/](medications/README.md) | 药物录入、计划与证据/图库 |
| [records/](records/README.md) | 记录与总结 |
| [care/](care/README.md) | 照护与跟进 |
| [experience/](experience/README.md) | 导航、布局、账户、引导和体验 |
| [platform/](platform/README.md) | 浏览器能力、技术诊断和外部适配 |
| [support/](support/README.md) | helper、synthetic 夹具与独立浏览器测试页面 |

在 frontend 运行 `npm run test:browser -- --list` 只列出用例，不执行服务操作。
运行单文件示例：`npm run test:browser -- platform/browserTts.spec.ts`。
注意 Playwright 文件过滤路径相对 e2e，文档完整路径也可用于过滤。

`QA_BASE_URL` 指向已启动的测试前端，`PLAYWRIGHT_CHROMIUM_EXECUTABLE` 选择现有 Chrome/Edge。
各文件原有 RUN_* 显式开关保持不变；请阅读目标文件开头，确认使用本地内存、HTTP mock、
真实 SQL、外部 provider 还是设备。外部/真实数据测试不会因目录整理而自动启用。
support 中的 HTML/TSX 页面只用于本地 Vite 验收，不是产品路由，不导入生产入口。
输出由 playwright.config.ts 写到仓库 outputs/playwright-results，不提交。

## 文件命名与合并规则

`knowledge.spec.ts` 表示药物知识的浏览器测试；`.spec.ts` 是测试文件后缀（specification），不是页面或生产脚本。
单元/组件测试使用 `.test.ts(x)`。二者均保留测试运行器惯例，并在目录说明中标明用途。
同一领域中不再重复目录名：`assistant/knowledge.spec.ts`、`records/layout.spec.ts`。
TypeScript 工具、Hook 和测试使用 camelCase；组件使用 PascalCase。文件名描述长期职责，不用 a/a1、会话编号或“refinement”作为版本名。

同一页面且数据装配、运行条件相同的场景放同一文件，用 `test.describe` 分组。
HTTP mock、本地应用 API、真实 SQL 和 provider 验收分别保留，避免一次运行混用不同服务。
历史的两份 polish 套件已按页面归属拆并进布局、记录和照护；共用 mock 改名为 patientAppFixture。
旧 session045/ux-navigation 中依赖八步引导/旧表单的四个场景、旧 medithread-rc 的两个场景已退役；
现役六步引导、录入、来源/剂量核对、会话和记录测试继续覆盖对应功能，并增加当前本地导航/草稿与日历导出两项验收。
照片选择及 Back/Forward 恢复的独立场景已迁移到当前导航套件。
现有单元、组件、mock 与应用 API 检查分别提供证据，不能将它们称为旧完整真实内存流程已全部重放。
RC 原意是 release candidate（发布候选），历史阶段名不再作为现役文件名。

Playwright 发现文件表示它在测试集合中，不代表它在 CI 或日常启动时执行。运行 `--list` 不能证明浏览器行为通过。
本目录没有证据证明所有真实环境套件最近均已运行；以实际验收记录为准。
