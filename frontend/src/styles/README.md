# 样式

统一 CSS 入口和共享/患者页面样式；本轮保留现有选择器和导入顺序。

| 文件 | 职责 |
|---|---|
| [app.css](app.css) | 现有患者页面样式，保留层叠顺序 |
| [base.css](base.css) | 元素默认样式、可访问性和重置 |
| [components.css](components.css) | 共享控件样式 |
| [followups.css](followups.css) | 跟进和补记页面样式 |
| [index.css](index.css) | 全局样式唯一入口，保持加载顺序 |
| [records.css](records.css) | 记录页面样式 |
| [tokens.css](tokens.css) | 颜色、字号、间距和布局令牌 |
| [startup.css](startup.css) | 非临床启动框架；Vite 从同一令牌源内联关键样式，完整应用下载前即可显示 |

同目录 `*.test.ts(x)` 是 Vitest 单元/组件回归。新增文件按职责归属；依赖规则由 `npm run check:architecture` 检查。
