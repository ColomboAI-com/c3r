# Operator-local credential recovery

The key-management CLI can now create a credential-only SQLite snapshot and restore
it into a **new** database. This implements the local backup/restore boundary, not
deployed encryption, a backup schedule, copy deletion, or an actual production drill.

## Safety contract

- Copy organizations, project rate limits and hash-only key records in one SQLite
  read transaction. Do not copy quota windows, usage records or request audit history.
- Reject missing sources, linked paths and existing destination files. POSIX private
  directory/file checks remain in force; Windows ACLs require deployment verification.
- Return the completed snapshot's SHA256, counts and scope, never plaintext keys.
- Require the approved snapshot SHA256 on restore and a versioned snapshot marker.
  The hash must come from the approved receipt, not be recomputed to bless a changed file.
- Restore only a bounded, standalone snapshot (at most 64 MiB), rejecting WAL, SHM
  and journal sidecars. Deserialize the exact hash-verified bytes into read-only
  in-memory SQLite; never reopen the source pathname to obtain recovery rows.
- Backup opens the existing database read-only, validates its credential schema and
  uses one read transaction. An empty or wrong source is an error, not a new database.
  Hard-linked files and redirected/junction paths are rejected at the recovery boundary.
- Revoke **all restored keys**. An older backup cannot establish revocations made
  after it was taken. Issue replacement scoped keys through the secure delivery
  workflow before reopening ingress; no option silently reactivates snapshot keys.
- Preserve the original database and snapshot. Recovery never overwrites the live
  database. An unsuccessful copy may leave a reserved empty database; quarantine it
  and use a new path after diagnosis, rather than reusing it as a valid snapshot.

## Commands (private operator terminal only)

Both source and destination must be absolute paths in approved private directories.
The destination must not exist. Provision and verify encrypted storage and its IAM
before copying real credentials; a SQLite file is not itself encrypted.

```sh
python -m c3r.key_management --database /private/live/access.sqlite3 \
  backup --destination /private/encrypted-backups/access-snapshot.sqlite3

python -m c3r.key_management --database /private/encrypted-backups/access-snapshot.sqlite3 \
  restore --destination /private/recovery/access.sqlite3 \
  --expected-sha256 APPROVED_SNAPSHOT_SHA256
```

Keep the backup hash and receipt in the approved private evidence channel. Backup
records contain credential hashes/salts and tenant identifiers: they are sensitive
even without plaintext keys. Never upload them to a public repository or log their
contents. Snapshot credentials preserve their absolute expiration and scope; restores
add revocation and require replacement keys rather than extending old expiration.

With ingress disabled, verify project isolation, expected credential counts, refusal
of old keys and successful authentication of securely delivered replacement keys.
Switch the configured database only through the reviewed service recovery procedure.
Quota windows restart in the new database; do not use recovery to evade rate limits.

## Remaining deployment evidence

The production gate still requires actual encrypted-volume/IAM readbacks, encrypted
backup destinations, a scheduled snapshot job, inventory of every copy/version,
retention and deletion evidence, tested restoration and key delivery, and a live
rollback drill. Receipts deliberately report `encryption_verified=false` and
`backup_deletion_verified=false`. This implementation does not enable production,
research collection, MC-1 or `/v1/c3r/execute`.
