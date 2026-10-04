# Encrypted portable Neon / GCS recovery

2026-10-03. Operator-only tooling; real cloud-to-local recovery remains pending.

The archive contains canonical PostgreSQL rows at current Alembic head and referenced private file bytes, with schema/scope/source timestamps and integrity hashes. Finance is single-user, without per-row ownership; the configured scope must match the bound principal. Sessions, auth credentials and unfinished worker state are excluded. Original content-addressed files remain immutable and retained during export. Pause all writers/workers; PostgreSQL snapshot consistency alone cannot make independently mutable objects consistent.

Archive encryption uses the existing chunked AES-256-GCM authenticated format and passphrase KDF. Passphrases are entered interactively, never placed in command arguments/environment/evidence. Keep archives in protected storage and passphrases separately in a user-controlled password manager/recovery channel. A forgotten passphrase cannot be recovered. The CLI does not upload archives or enforce retention automatically.

## Export and verify

Inject production runtime DATABASE_URL and GCS/OIDC settings securely; use the configured owner scope. The runtime has object-read access. Run from services/api (or `uv run --directory services/api --locked`):

```sh
python -m app.recovery.cli export --output /secure/finance.pfarchive --scope-id <configured-scope>
python -m app.recovery.cli verify --archive /secure/finance.pfarchive
```

Do not put an archive inside the frontend/public tree. Export reads only supported canonical head schema and verifies every referenced object's length/hash; missing/changed bytes fail. Record the secret-free verification summary and archive hash. The existing bounded resumable restore retains atomic visibility and rechecks content.

## Isolated restore

Create an empty loopback PostgreSQL database named `pf_restore_<unique-name>` and apply Alembic head. Set PF_RESTORE_DATABASE_URL only for restore, pointing to that isolated target. Use a fresh owner-only directory outside the application/public tree.

```sh
python -m app.recovery.cli restore --archive /secure/finance.pfarchive \
  --target-private-dir /secure/restored-finance \
  --source-scope-id <archive-scope> --target-scope-id <approved-target-scope> \
  --acknowledge-target pf_restore_<unique-name>
```

Non-loopback targets, wrong schema/scope/acknowledgment, non-empty targets without the exact resume identity, unsafe files or tampered archives fail. Restore uses unpublished staging and bounded batches before final visibility, private 0600 resume markers, hash/count checks and cyclic FK pointer repair. Repeating/resuming the same archive is idempotent; a different archive cannot resume it. Restored sessions remain excluded; bind/test the intended owner before hosted reuse.

Run normal report/exposure/net-worth/history/lots/research checks against the restore target and compare originals/counts/hashes. A local synthetic drill proves local portability, not cloud permissions or a production RPO/RTO. Before real data, export from an approved isolated Neon branch + private GCS bucket and restore locally, then approve tested archive schedule/retention, passphrase custody, RPO (last verified snapshot timestamp) and measured RTO. Neon-managed restore/history is separate from this portable backup and subject to its selected plan.
