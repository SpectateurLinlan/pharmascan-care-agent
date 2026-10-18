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
