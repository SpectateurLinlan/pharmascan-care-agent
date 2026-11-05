# 共用夹具与测试页面

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [navigation.ts](navigation.ts) | 显式跳过初次引导的共用浏览器 helper | 见文件头和测试数据装配；不自动启用真实服务 |
| [patientApp.html](patientApp.html) | Vite 本地测试页面（?shell=1 使用真实 App） | 见文件头和测试数据装配；不自动启用真实服务 |
| [patientAppFixture.ts](patientAppFixture.ts) | 共用 synthetic Auth/HTTP 与测试数据控制器 | 见文件头和测试数据装配；不自动启用真实服务 |
| [patientAppHarness.tsx](patientAppHarness.tsx) | 真实组件的独立测试挂载入口 | 见文件头和测试数据装配；不自动启用真实服务 |
| [pushSettings.html](pushSettings.html) | 通知组件的本地测试页面 | 见文件头和测试数据装配；不自动启用真实服务 |
| [pushSettings.tsx](pushSettings.tsx) | 通知设置的独立组件挂载 | 见文件头和测试数据装配；不自动启用真实服务 |
