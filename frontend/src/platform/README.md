# 浏览器能力

语音、音频和通知适配；后端副作用通过显式端口注入。

## 子目录

| 目录 | 内容 |
|---|---|
| [notifications/](notifications/README.md) | 标签页提醒和显式后端端口的推送适配 |
| [speech/](speech/README.md) | 语音识别、合成与音频编码 |



同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
