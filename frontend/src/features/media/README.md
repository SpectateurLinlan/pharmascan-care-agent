# media

照片、原始来源、图库、PDF 和图像对比。

| 文件 | 职责 |
|---|---|
| [imageRouting.ts](imageRouting.ts) | 来源照片与药片证据的路由模型 |
| [MediaMetadataFields.tsx](MediaMetadataFields.tsx) | 照片/PDF 标题、分类和来源描述字段 |
| [MedicationLibraryFileManagement.tsx](MedicationLibraryFileManagement.tsx) | 原生图库和 PDF 的管理动作 |
| [PendingEvidenceTasks.tsx](PendingEvidenceTasks.tsx) | 未完成来源/草稿列表和受限删除 |
| [PersonalGalleryScreen.tsx](PersonalGalleryScreen.tsx) | 个人药物图库浏览与上传 |
| [PhotoAcquisition.tsx](PhotoAcquisition.tsx) | 相机/文件选择与照片输入 |
| [photoEvidence.ts](photoEvidence.ts) | 从照片响应构造聊天证据上下文 |
| [PrintedLabelEvidence.tsx](PrintedLabelEvidence.tsx) | 印刷标签证据和待核对内容 |
| [PrivateEvidencePhoto.tsx](PrivateEvidencePhoto.tsx) | 私有原图的限时读取与展示 |
| [SourcePreviewScreen.tsx](SourcePreviewScreen.tsx) | 来源证据预览页面 |
| [sourceReviewHintModel.ts](sourceReviewHintModel.ts) | 原标签待核对文字的纯提取模型 |
| [SourceReviewHints.tsx](SourceReviewHints.tsx) | 未确认的原标签时间、释药和疗程提示 |
| [VisualCheckScreen.tsx](VisualCheckScreen.tsx) | 药物照片比较页面；不确认药物身份或已服用 |

`*.test.ts(x)` 为本功能单元/组件回归。公开复用路径见 `frontend/architecture.config.mjs`；不在这里复制其他 owner 的业务逻辑。
