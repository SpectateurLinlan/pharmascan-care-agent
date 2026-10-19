# 本地已登录浏览器诊断修复 — 2026-10-19

## 已确认的问题与未确认的部分

旧 `scripts/qa/medication_counts_in_browser.js` 不是应用的认证权威。它扫描 localStorage 的 `supabase.auth.token` 和所有 `sb-…-auth-token`，要求恰好一个结果，并自行判定 `expires_at`。另一个项目/旧会话键就能让有效登录被判为BLOCKED；过期快照也不能替代SDK正在恢复/续期后的状态。真实Chrome、实际Auth SDK、模拟Auth/API的两种情景已重现并通过修正后的路径。不能据此认定用户的真实浏览器具体触发了哪一个旧条件；没有读取用户浏览器的凭据或存储内容。

实际应用：`frontend/src/api/auth.ts` 只创建一个GoTrueClient；没有自定义storageKey/storage适配器，安装的auth-js默认key为`supabase.auth.token`，支持持久化及自动续期，存储不可用时可退到内存。正常API在请求前等待该实例的`getSession()`，由SDK处理初始化、锁和临近过期续期；诊断绕过这条链路，不能以它的结果证明用户未登录。没有为本修复创建第二个Auth客户端，也没有变更现有存储key。

对401/503另外确认了一处服务端分类问题：`SupabaseAuthApiVerifier` 对每次请求用已有Bearer调用配置项目的`GET /auth/v1/user`，超时5秒。原实现把所有HTTP错误、网络/超时以及无效JSON都归为401，包括Auth服务5xx。这不是可靠的“退出登录”证据。现在只有Auth服务明确401/403仍映射401；429、5xx、其他非预期HTTP错误、网络/超时及无效响应映射503/PROVIDER_UNAVAILABLE。身份验证失败时仍不访问患者仓库，不返回成功、不绕过RLS、不放宽token校验。不自动重试认证或患者写入。

**尚未确认：** 用户之前Today/Alerts请求具体是token被拒绝、请求头缺失、Auth服务不可达、Data API拒绝，还是其他503。没有访问现有浏览器用户会话或该次服务器日志，不能从Console状态码反推。磁盘前后端Supabase URL一致仅是配置证据，不证明当前进程配置或token签发项目。未认定发生token-refresh race；合成Chrome验证了SDK续期期间诊断会等待并使用续期后的凭据。

## 实现边界

- 认证：新增同一gateway的`getExistingAccessToken()`，无会话时返回null，不调用`signInAnonymously`。正常应用的匿名bootstrap行为保持不变。
- API：计数复用现有`fetchResponse`的认证、超时、错误封装，入口只接受两个固定GET路径，禁止跟随重定向。不向Console暴露token、用户、raw Response或记录。
- 开发入口：仅Vite DEV并且origin精确为`http://localhost:5173`或`http://127.0.0.1:5173`时注册`window.medithreadMedicationCounts`。函数没有URL/方法参数，只返回安全摘要；重复执行中的调用复用同一个Promise。
- 输出：计数GET的HTTP状态、有限结果类别、item_count及真实state分组；未知state折叠为`unsupported_state`，错误计数为null，不冒充0条有效记录。
- 观察：现有API封装对四条白名单路径发送开发事件，只保留path（无query）、HTTP状态、是否附带Bearer的布尔值及有限失败阶段。只保留每路径最后一次已观察响应，不保留请求头、错误原文、响应记录或时间线。未观察到不是健康证明。
- 不额外探测Today/Alerts。特别是Alerts既有GET会materialize规则剂次，因此诊断不能为了排错重复触发它。诊断只观察页面原本的请求。
- GET约束指患者业务请求。SDK可以按应用原有授权流程进行正常Auth续期（identity token POST），没有显式调用refreshSession、登录/OTP、匿名开户、登出或患者写入。

## 使用步骤

1. 保存当前未提交的表单内容，在已经登录的`http://localhost:5173`开发页面刷新一次。**不要退出登录，也不要删除localStorage。** 刷新使主入口加载修正后的开发诊断；无需手工导入模块或新建Supabase客户端。
2. 打开Chrome DevTools → Console，复制并执行仓库中的整个 `scripts/qa/medication_counts_in_browser.js`。该脚本仅调用应用已经注册的安全函数。也可直接执行下面这段：

```js
void window.medithreadMedicationCounts().then(result => {
  console.info(result.result);
  console.table(result.endpoints.map(row => ({
    ...row, states: row.states ? JSON.stringify(row.states) : null
  })));
  console.table(result.observed_requests);
});
```

3. 第一张表为`/api/me/medications`与`/api/me/regimens`，没有药名/ID或记录内容。第二张表为页面正常请求的最新安全状态。要观察Today，正常打开Today页面后再执行；不要在Console手动发送Alerts或服药请求。
4. 如提示诊断未加载，确认是上述origin、Vite开发服务而非production build/preview，刷新后重试；该提示不代表退出登录。origin错误会直接拒绝，不发送请求。
5. 可以分享这两张摘要表。不要分享Authorization、Cookies、localStorage、JWT、HAR或Network原始患者响应。本轮没有取得真实患者计数，也不把模拟测试结果替代它们。

后端错误分类修改仅在载入新Python代码的本地进程生效；本轮没有重启/停止用户现有服务。`scripts/start_dev.py`默认会重载backend/app源码；如果原进程以no-reload启动，沿用该进程原来的本地启动方式重启API后才有新分类。不要另起同端口第二套服务或改生产配置。前端诊断也识别旧后端的已知401错误文案，以便在重启前区分这一历史分类路径。

## 如何解释摘要

| 字段/结果 | 可得结论 | 不能推断 |
|---|---|---|
| `complete` / 两个200 | SDK现有会话在本次计数读取中有效，返回真实数量 | 之前401从未发生或所有业务功能健康 |
| `sdk_session_unavailable` | SDK这次未提供现有会话，未发送无认证请求、未创建身份 | 用户必然退出、应删除存储或强制重新登录 |
| `session_or_network_unavailable` | 取得会话/传输发生错误，细节不公开 | 登录失效或0条患者记录 |
| `authorization_attached=true` | 应用fetch确实附带了Bearer | 服务端一定收到了、该token一定被接受 |
| `missing_bearer` | 后端明确报告缺少Bearer | 应用用户已登出；若前端true应另查代理/实际请求链 |
| `identity_rejected` | Auth服务明确401/403 | 仅凭此确定过期、项目不匹配或撤销的具体原因 |
| `legacy_identity_service_failure_401` | 旧后端把无法验证身份映射为401 | token已被明确拒绝 |
| `identity_service_unavailable` | 新后端报告身份服务无法完成验证 | 患者不存在或数据为空 |
| `data_api_auth_rejected` | 后续Data API拒绝认证访问 | 必然缺少migration或应该禁用RLS |
| 其他503 / `unknown` | 依赖不可用/未定位阶段，需要进一步安全证据 | 自动归因于Auth、031或用户输入 |

## 验收与实际证据

| 行为 | 拥有者/接口 | 验证环境与结果 |
|---|---|---|
| 有效会话不受无关存储键影响 | Auth gateway → existing-only API →聚合函数 | PASS：实际Chrome/SDK，模拟Auth/HTTP |
| 等待SDK续期、不额外登录 | 相同gateway/client；显式单次诊断 | PASS：Chrome实际SDK续期，Auth HTTP模拟；无真实token |
| 只GET计数、被动观察Today/Alerts、无敏感输出 | localDiagnostics/diagnosticContract/Console脚本 | PASS：unit及Chrome，未以真实患者执行 |
| 401与503区分且不访问患者仓库 | SupabaseAuthApiVerifier/public error envelope | PASS：合成provider failures及认证回归 |
| 生产不注册诊断入口 | main.tsx DEV条件及生产bundle | PASS：构建及产物字符串检查；未部署 |
| 用户原先几次401/503的精确原因 | 实际本地浏览器/服务端 | NOT VERIFIED，须修正后安全摘要，不假设登出或刷新竞争 |

实际执行记录位于Git忽略的`outputs/auth-diagnostic/`：相关后端回归110通过（其中认证边界/新负向30通过，重叠不相加）；完整前端317通过/56文件；Chrome3通过；Typecheck、ESLint、Vite build、针对改动的Ruff/format和diff检查。Chrome和provider tests都是合成Auth/API，不是真实患者/托管Auth验收。初次前端执行在源码补充新export期间出现旧模块版本断言失败，最终完整重跑已通过；旧日志保留，不以旧失败结果宣称最终PASS。

变更文件：`frontend/src/api/auth.ts`、`client.ts`、`diagnosticContract.ts`（新）、`localDiagnostics.ts`（新）、`localDiagnostics.test.ts`（新）、`auth.test.ts`、`frontend/src/main.tsx`、`vite-env.d.ts`（新）、`frontend/e2e/auth-diagnostic.spec.ts`（新）、`scripts/qa/medication_counts_in_browser.js`、`backend/app/transport/auth.py`、`tests/backend/test_auth_provider_failures.py`（新）、本文及REQUIREMENTS/DEFERRED_WORK补充。没有修改History、Release A实现、feature flags、迁移、RLS或Storage。无Git写操作、生产操作或部署；现有其他修改保留。

建议本轮独立提交范围为上述诊断/Auth错误分类及测试文档，消息`fix(auth): diagnose existing sessions without storage guesses`；尚未授权或执行暂存/提交。后续仅需真实用户运行安全摘要以定位剩余Auth问题，不需要密钥或权限变更。
