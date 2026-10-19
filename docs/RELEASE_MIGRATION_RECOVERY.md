# 027–029 migration execution and recovery

Owner authorized production execution on 2026-10-19, after backup and restore
verification. This document is an operator procedure, not permission for future
production actions. Never replay 001–026 or run an unrestricted migration command.

## Preconditions and execution

- Match configured Supabase project, live ledger and canonical LF-normalized SQL
  hashes to the reviewed manifest. Check actual functions, policies and ACLs.
- Use PostgreSQL 17 official tools. Keep the backup outside the repository, with
  directory inheritance disabled and access restricted to the owner and SYSTEM.
  The custom archive includes database schema, data, ACLs and migration history;
  the roles export intentionally excludes role passwords.
- Validate archive readability and restore `public`, `auth` and `storage` into a
  password-protected localhost instance. Compare every restored table's row count
  and content digest against the same exported production snapshot. Do not expose
  row contents, private tool logs or database credentials in project reports.
- Storage object bytes, platform secrets/settings, PITR and runtime state are not
  recovered by this database procedure. The current schema-only changes do not
  call a deletion RPC or remove Storage objects.
- Invoke `scripts/db.py migrate --only VERSION` separately for 027, 028 and 029.
  After each, verify ledger hash and actual contracts before proceeding. Keep
  later migrations outside this authorization, even if discovered in the tree.

The opt-in tools are `scripts/qa/pre_migration_backup.py` and
`scripts/qa/execute_release_migrations.py`; read their flags and safety checks
before running. Backup/restore validation is not a production restore command.

## Failure handling

Each migration has its own transaction. A failure inside it rolls back that file;
the runner records its ledger entry afterwards. If the connection fails between
DDL commit and ledger insert, inspect both actual schema and ledger. Stop rather
than rerun non-idempotent DDL or manually claim it completed.

- **027:** prefer keeping its protected receipt and deletion RPC contract. If the
  new entry must be suspended, restrict RPC execution using a separately reviewed
  forward repair; do not re-enable direct table DELETE. Restoring an application
  version cannot recover a deleted draft or a Storage object. No production delete
  acceptance test was authorized in this round.
- **028:** retain the added `REGIMEN_OVERLAP` audit code. An application rollback
  does not require removing a backward-compatible allowlist value.
- **029:** investigate the actual denied operation and add only the required
  scoped privilege or controlled RPC in a reviewed forward repair. Never restore
  blanket anonymous access, TRUNCATE, MAINTAIN or unguarded evidence writes merely
  to remove an error. Existing conversation append and private image retirement
  use guarded RPCs; Push subscription removal is a scoped UPDATE.
- A full restore is a last resort requiring independent authorization, a stopped
  and reviewed write path, the correct platform environment, reconciliation of
  post-backup changes and a separate Storage recovery plan. Do not run the local
  restore procedure against production or restore NOLOGIN test roles there.

Database upgrade is not application deployment. Publish a compatible backend
before the frontend, then perform approved hosted Auth/Storage/device acceptance.

## 030 successor activation — applied, application release separate

Migration 030 is outside the earlier 027–029 authorization. On 2026-10-19, the owner authorized a fresh read-only backup only; that authorization did not include migration execution. A protected PostgreSQL 17.11 archive was created and verified by restoring it locally: all 70 table fingerprints matched. The archive and restore logs remain outside Git. The separate verification report is `outputs/release/backup-verification-pre030-20261019.json`; the prior canonical report was preserved byte-for-byte. The archive does not contain Supabase Storage object bytes, platform secrets, network/Cron state or PITR.

After the owner explicitly approved migration 030 in this workflow, an immediate transaction-read-only recheck confirmed 027–029 exact hashes, 030 pending at SHA-256 `0a70cce51e55ec417956b30a7cf59f64e2a51f582b1af1b03ae9958def59d060`, and the RPC absent. The scoped command `python scripts/db.py migrate --only 202610190030` then applied only 030. Post-apply read-only metadata confirms all four hashes match, the RPC and overlap trigger exist, and no patient rows were read. No app deployment or production patient-data smoke write was performed.

The transaction adds `activate_medication_regimen_version(uuid,uuid,text)` and replaces `core_guard_regimen_overlap()`. It does not change tables, RLS policies, Storage policies or existing rows. The RPC is `SECURITY DEFINER` with a fixed `search_path`. Production ACL inspection shows EXECUTE for `authenticated`, `service_role` and the `postgres` owner; `anon` and `PUBLIC` are denied. The `service_role` grant comes from Supabase function default privileges and was not revoked by this migration; keep that credential server-only. The rollback script drops the RPC and restores the prior overlap guard. Local PostgreSQL 17.11 rollback/re-apply acceptance passed. This rollback does not reverse any regimen activation already performed through the new RPC; after use, prefer a reviewed forward repair unless it is confirmed no activation was written.

The compatible backend currently exists in the working tree and calls this RPC, but hosted runtime SHA is not verified. The database migration is applied; any backend release that invokes it remains separately approved and must follow this migration. Database migration is not application deployment. If a future execution loses connection between DDL commit and ledger recording, inspect the live ledger and RPC/trigger definitions and stop; do not blindly rerun or invoke rollback.


## 2026-10-19 atomic local runner verification supplement

`apply_recorded_migration` now wraps migration body and ledger insertion in one transaction with an advisory transaction lock, checks reviewed SQL/prerequisite hashes, and refuses inner transaction controls. Outer BEGIN/COMMIT wrappers are removed only for execution; migration source hashes stay unchanged. The actual scoped031 -> 032 -> 033 runner and deliberately failed031 ledger insertion passed on disposable local PostgreSQL, including DDL rollback, repeat application and concurrent submissions. A connection loss still requires object/ledger inspection, not an automatic retry or destructive rollback. Older paragraphs describing a normal DDL/ledger commit gap are historical.

This is local verification, not production execution or approval. See [final integration](LOCAL_INTEGRATION_VERIFICATION.md) for Auth/Storage/recovery blockers and the separately authorized future rollout.
