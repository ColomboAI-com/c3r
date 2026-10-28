"""Operator-local key administration. Only `issue` emits a key, once, to stdout.

Use a secure terminal/secret-manager delivery channel; never redirect the issued
key into source control or ordinary logs. This CLI is not a public admin API.
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from .api_access import AccessStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("project", "issue", "keys", "revoke", "usage"):
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
    args = parser.parse_args()
    try:
        store = AccessStore(args.database)
        if args.command == "project":
            store.create_project(args.tenant, args.project, rpm=args.rpm, key_rps=args.key_rps)
            result: object = {"status": "created"}
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
        else:
            result = store.project_usage(args.tenant, args.project)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"error": "key administration failed; check private database and inputs"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
