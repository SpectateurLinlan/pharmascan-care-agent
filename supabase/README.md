# 数据库变更资料

| 子目录 | 内容与边界 |
|---|---|
| [migrations/](migrations/README.md) | 按版本顺序的 PostgreSQL/Supabase 迁移 SQL |
| [rollback/](rollback/README.md) | 对应回退 SQL；可能因保护历史数据主动拒绝破坏性回退 |
| [review/](review/README.md) | 待单独核准的审阅 SQL，不属于自动上线迁移 |

脚本入口已归类到 scripts/operations/db.py；目标核对、备份和迁移执行遵守独立授权。
目录整理不执行 SQL，不修改 Auth/RLS/Storage 策略或线上配置。
