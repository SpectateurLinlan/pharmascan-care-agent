# messages

纯词典/翻译及偏好上下文；应用从 app 注入 PreferencesPort。

| 文件 | 职责 |
|---|---|
| [aboutCopy.ts](aboutCopy.ts) | 关于应用相关双语词条 |
| [catalog.ts](catalog.ts) | 词典注册，严格保留原有覆盖顺序 |
| [experienceCopy.ts](experienceCopy.ts) | 交互体验相关双语词条 |
| [patientCopy.ts](patientCopy.ts) | 患者操作相关双语词条 |
| [pushCopy.ts](pushCopy.ts) | 设备推送相关双语词条 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
