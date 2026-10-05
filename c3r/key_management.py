"""Operator-local key administration. Only `issue` emits a key, once, to stdout.

Use a secure terminal/secret-manager delivery channel; never redirect the issued
key into source control or ordinary logs. This CLI is not a public admin API.
"""
import argparse
import hashlib
import hmac
import json
import re
import sqlite3
import time
from pathlib import Path

from .api_access import AccessStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--destination", type=Path, required=True)
        if name == "restore":
            command.add_argument("--expected-sha256", required=True)
    for name in ("project", "issue", "keys", "revoke", "usage", "purge"):
        command = commands.add_parser(name)
        command.add_argument("--tenant", required=True)
        command.add_argument("--project", required=True)
        if name == "project":
            command.add_argument("--rpm", type=int, default=60)
            command.add_argument("--key-rps", type=int, default=10)
        elif name == "issue":
            command.add_argument("--scope", action="append", required=True)
            command.add_argument("--live", action="store_true")
            command.add_argument("--ttl-seconds", type=int, default=86400)
        elif name == "revoke":
            command.add_argument("--key-id", required=True)
        elif name == "purge":
            command.add_argument("--retention-seconds", type=int, required=True)
            command.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    try:
        if args.command in {"backup", "restore"} and not args.database.is_file():
            raise ValueError("existing credential source required")
        if args.command == "restore":
            AccessStore.validate_path(args.database)
            if re.fullmatch(r"[a-f0-9]{64}", args.expected_sha256) is None:
                raise ValueError("approved backup hash required")
            with args.database.open("rb") as artifact:
                digest = hashlib.file_digest(artifact, "sha256").hexdigest()
            if not hmac.compare_digest(digest, args.expected_sha256):
                raise ValueError("credential backup hash mismatch")
        store = AccessStore(args.database)
        if args.command in {"backup", "restore"}:
            result: object = store.copy_credentials(args.destination, restore=args.command == "restore")
        elif args.command == "project":
            store.create_project(args.tenant, args.project, rpm=args.rpm, key_rps=args.key_rps)
            result = {"status": "created"}
        elif args.command == "issue":
            if not 1 <= args.ttl_seconds <= 31536000:
                raise ValueError("bounded key expiration required")
            issued = store.issue_key(args.tenant, args.project, set(args.scope), live=args.live,
                                     expires_at=time.time() + args.ttl_seconds)
            result = {"api_key_id": issued.key_id, "api_key": issued.secret, "show_once": True}
        elif args.command == "revoke":
            store.revoke_key(args.tenant, args.project, args.key_id)
            result = {"status": "revoked"}
        elif args.command == "keys":
            result = store.list_keys(args.tenant, args.project)
        elif args.command == "purge":
            result = store.purge_metadata(args.tenant, args.project,
                                          retention_seconds=args.retention_seconds, limit=args.limit)
        else:
            result = store.project_usage(args.tenant, args.project)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"error": "key administration failed; check private database and inputs"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
