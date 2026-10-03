# Stage 4 encrypted export and local recovery

**Status:** Recovery tooling and synthetic PostgreSQL drill prepared locally; no real DSQL, S3, or cloud recovery has run  
**Updated:** 2026-10-03

## Archive contract

The operator CLI creates a versioned .pfarc archive. It contains the current
finance tables, source lineage, publication/review revision identities,
NUMERIC values as base-10 strings, currency codes, UTC-normalized microsecond
timestamps, private original files, and immutable report artifacts. A schema
fingerprint, table/row hashes and counts, object sizes and reference counts,
and foreign-key lineage are inside the encrypted manifest. The source database
is read in one read-only REPEATABLE READ transaction. After that transaction,
file objects are loaded by immutable content key and checked against their
captured hashes and sizes; a missing or changed object aborts the export.

The archive uses chunked AES-256-GCM with a per-archive random salt and nonce
prefix, Scrypt (N=32768, r=8, p=1), and authenticated chunk sequence and
length. The manifest and file contents are encrypted. The randomly generated
salt and nonce prefix are in the file header; the passphrase is entered at a
terminal prompt and is never accepted as a command-line argument or written to
the archive or output. Keep the passphrase separately in a user-controlled
password manager or other protected recovery channel. A forgotten passphrase
cannot be recovered. Do not store the archive passphrase in AWS Secrets
Manager beside the archive.

The tool caps a payload at 256 MiB, a stored object at 20,000,000 bytes, a
record at 1,000,000 bytes, a table at 500,000 rows, and an archive at 1,000,000
rows. It writes final archive files exclusively with mode 0600. Short-lived
plaintext work files are held in an owner-only 0700 temporary directory and
removed on normal completion. Ensure the operator host's temporary storage is
encrypted and has sufficient space; an abrupt power loss can leave that
private temporary directory for manual cleanup.

The single-user finance schema has no row-level owner column, so export
captures the explicitly confirmed whole-database personal scope. It retains
application-generated UUIDs and does not rewrite financial IDs. The archive
omits auth_principals, auth_sessions, security_audit_events, and jobs: target
identity is rebound deliberately, browser sessions do not transfer, audit
identities are not portable finance records, and a leased job must never
resume on a different environment. The restore marker records the
operator-confirmed source-to-target scope mapping without copying credentials
or user identity rows.

## Export and verify

Use a newly chosen output path that does not already exist. No server-side
export API or automatic upload is provided.

    cd services/api
    .venv/bin/python -m app.recovery.cli export \
      --scope-id '<confirmed-source-personal-scope>' \
      --output '/secure/recovery/finance-2026-10-03.pfarc'
    .venv/bin/python -m app.recovery.cli verify \
      --archive '/secure/recovery/finance-2026-10-03.pfarc'

Export uses the selected database and file adapter from the app's explicit
environment. With authentication enabled, the scope must equal the
server-configured personal scope. A production export reads through the
configured scoped application DSQL IAM role and private S3 role; it does not
use the migration/admin role. Verify a newly created archive before moving it
to a separately approved encrypted retention location. The CLI does not
provide a retention policy, auto-delete an earlier archive, or transfer data
to AWS.

Schedule a maintenance window: pause user writes and wait for any enabled
finance worker to settle before export. The current production worker remains
disabled pending separate DSQL lease evidence. The database rows are a
consistent database snapshot; immutable file objects are verified immediately
afterward. There is no live evidence yet for DSQL transaction duration,
concurrent user activity, S3 object retention, or cross-service recovery.

## Restore into isolated local PostgreSQL

Restore never creates a database, migrates a schema, merges records, deletes
rows, or targets a remote host. Prepare a new loopback PostgreSQL database
whose name begins pf_restore_, migrate it to the current Alembic head, and
choose a new empty private file directory whose final directory name exactly
matches the database name. Do not point either at the local application
database or its current file directory.

    cd services/api
    # Create the new database using the local PostgreSQL operator account.
    createdb --host 127.0.0.1 --port '<local-port>' --username '<local-role>' \
      pf_restore_recovery_20261003

    # Apply the current local schema before removing the migration URL.
    DATABASE_BACKEND=postgres \
    DATABASE_URL='postgresql+psycopg://<local-role>@127.0.0.1:<local-port>/pf_restore_recovery_20261003' \
      .venv/bin/alembic upgrade head
    unset DATABASE_URL

    # Supply the dedicated restore URL only to the recovery command.
    export PF_RESTORE_DATABASE_URL='postgresql+psycopg://<local-role>@127.0.0.1:<local-port>/pf_restore_recovery_20261003'
    .venv/bin/python -m app.recovery.cli restore \
      --archive '/secure/recovery/finance-2026-10-03.pfarc' \
      --target-private-dir '/secure/private/pf_restore_recovery_20261003' \
      --source-scope-id '<confirmed-source-personal-scope>' \
      --target-scope-id '<explicit-new-local-personal-scope>' \
      --acknowledge-target 'pf_restore_recovery_20261003'
    unset PF_RESTORE_DATABASE_URL

Use an empty isolated restore database with a current migration head. The
restore rejects a non-loopback URL, a database without the pf_restore_ prefix,
URL query options, a schema mismatch, any row in any application table, an
acknowledgement typo, a source-scope mismatch, or a target directory that does
not match the database name. It also refuses the configured application
database and private-file directory. It does not drop or modify an existing
database. PostgreSQL connection credentials stay in the process environment;
the command suppresses database-driver details from its output.

Before publication the full encrypted payload, schema, all row hashes and
counts, object hashes/sizes, references, and frozen revisions are validated.
Objects are copied to immutable content-addressed local files first. Financial
rows are inserted in batches of 200, each in its own committed transaction
inside a deterministic, archive-specific PostgreSQL staging schema. Selected
account snapshot pointers remain null until all snapshots and lines are staged;
the original pointers are then restored in bounded batches. Every staged table
is checked against the archive's row count and hash. Only after those checks pass
does one short transaction rename the empty target's current `public` schema to
an archive-specific retained backup name and rename the complete staging schema
to `public`. The application cannot see partial restore rows. If a process stops
between database batches, the target remains on its original empty schema and a
retry uses conflict-safe inserts to continue staging. If it stops after schema
publication but before updating the marker, retry verifies the published schema
and completes idempotently. The previous empty schema remains in the isolated
database for operator inspection; the recovery tool does not delete it.

A private 0600 restore marker records the archive hash, schema, database name,
explicit scope mapping, staging/backup schema names, and phase. Retrying with
the same archive and mapping resumes safely; a second completed invocation
verifies all rows and objects and returns idempotently. Changed rows, other
files, or a different mapping are rejected.

After restore, run the normal report and reconciliation checks against the
isolated database, inspect original file previews, and compare the report
artifact/hash and counts with the encrypted manifest before deliberately
changing the local app configuration. The tool does not switch the app to the
restore target. The synthetic drill validates $25,000 NAV and reconciled
exposure, original statement bytes, frozen report bytes, interruption after a
committed database batch, hidden partial staging, bounded recovery retry,
tamper/wrong-key rejection, schema mismatch, missing/tampered objects, and
repeat idempotency. It is synthetic PostgreSQL evidence only; no DSQL source or
S3 object was used.

## Recovery objectives and remaining gates

No numeric RTO or RPO has been selected. Until an operator selects and tests
an export schedule, the recovery point is the timestamp in the last verified
archive; writes after it must be re-imported or recreated deliberately. Restore
time depends on the encrypted payload and local PostgreSQL/storage speed and
is not benchmarked. S3 source objects have no lifecycle deletion rule, and no
AWS Backup method has been selected or rehearsed. Do not describe DSQL
point-in-time recovery, immutable S3 retention, or a local-only drill as a
verified backup.

Before real production data is allowed, run export from an approved isolated
DSQL cluster and private S3 bucket, restore to a fresh isolated local
PostgreSQL database, reproduce golden Decimal NAV/exposure and source links,
record the immutable build/schema/config/fixture hashes and exact object
counts, and have the user/operator approve the tested retention, passphrase,
RTO/RPO, budget, and recovery ownership. Real DSQL and cloud recovery remain
unverified until that drill is completed with an approved target and spend
envelope.
