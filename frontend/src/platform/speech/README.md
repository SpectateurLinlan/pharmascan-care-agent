# speech

语音、音频和通知适配；后端副作用通过显式端口注入。

| 文件 | 职责 |
|---|---|
| [browserSpeech.ts](browserSpeech.ts) | 浏览器 SpeechRecognition 类型、能力和错误适配 |
| [browserTts.ts](browserTts.ts) | 浏览器 SpeechSynthesis 语音、播放/停止和速率适配 |
| [speech.ts](speech.ts) | 音频 WAV 编码与录音格式规范化 |

`*.test.ts(x)` 验证同名模块；保持纯契约与 I/O 的分离。
