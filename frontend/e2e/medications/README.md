# 药物与证据

范围与术语见 [测试说明](../README.md)。同文件用 describe 分组保持场景独立。

| 文件 | 验证什么 | 运行条件 |
|---|---|---|
| [detail.spec.ts](detail.spec.ts) | 药物详情的信息和操作边界 | 见文件头和测试数据装配；不自动启用真实服务 |
| [enrollment.spec.ts](enrollment.spec.ts) | 药物录入与字段收集 | 见文件头和测试数据装配；不自动启用真实服务 |
| [entryManagement.spec.ts](entryManagement.spec.ts) | 录入方式、退出、删除草稿与散片入口 | 见文件头和测试数据装配；不自动启用真实服务 |
| [gallery.spec.ts](gallery.spec.ts) | 图库/文件管理、私有预览、删除及历史导航 | 见文件头和测试数据装配；不自动启用真实服务 |
| [galleryProvider.spec.ts](galleryProvider.spec.ts) | 图库、来源冲突及真实视觉服务完整演示 | `RUN_GALLERY_DEMOS` |
| [galleryThumbnails.spec.ts](galleryThumbnails.spec.ts) | 私有缩略图解码与刷新 | `RUN_LIVE_BROWSER` |
| [intervalStart.spec.ts](intervalStart.spec.ts) | 间隔用药默认首次时间与核对 | 见文件头和测试数据装配；不自动启用真实服务 |
| [ocrReviewHints.spec.ts](ocrReviewHints.spec.ts) | OCR 候选与未确认内容的可读提示 | 见文件头和测试数据装配；不自动启用真实服务 |
| [persistence.spec.ts](persistence.spec.ts) | 真实账户中的药物持久化和患者隔离 | `RUN_LIVE_BROWSER` |
| [regimenGuards.spec.ts](regimenGuards.spec.ts) | 计划确认与安全边界 | `RUN_LOCAL_REGIMEN_QA` |
| [regimenHistory.spec.ts](regimenHistory.spec.ts) | 药物计划版本历史 | 见文件头和测试数据装配；不自动启用真实服务 |
