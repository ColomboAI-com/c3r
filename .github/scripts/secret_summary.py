"""Publish counts/identities only; never publish secret matches or raw errors."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def reject_constant(_value: str) -> object:
    raise ValueError()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--image-source-commit', required=True)
    parser.add_argument('--scanner-outcome', required=True)
    args = parser.parse_args()
    summary = {'scan_complete': False, 'secret_count': None,
        'image_id': args.image_id, 'source_commit': args.source_commit,
        'image_source_commit': args.image_source_commit,
        'source_binding': 'ci_observed_image_revision_label_and_checkout'}
    try:
        if (re.fullmatch(r'sha256:[0-9a-f]{64}', args.image_id) is None
                or re.fullmatch(r'[0-9a-f]{40}', args.source_commit) is None
                or args.image_source_commit != args.source_commit
                or args.scanner_outcome != 'success'):
            raise ValueError()
        with args.input.open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError()
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if (data.get('SchemaVersion') != 2 or data.get('ArtifactType') != 'container_image'
                or data.get('Metadata', {}).get('ImageID') != args.image_id):
            raise ValueError()
        results = data.get('Results')
        if results is None:
            results = []
        if not isinstance(results, list):
            raise ValueError()
        count = 0
        for result in results:
            matches = result.get('Secrets')
            if matches is None:
                matches = []
            if not isinstance(matches, list):
                raise ValueError()
            count += len(matches)  # Never inspect, stringify or export matches.
        summary.update(scan_complete=True, secret_count=count,
                       report_sha256=hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        pass
    args.output.write_text(json.dumps(summary, sort_keys=True) + '\n', encoding='utf-8')
    return 0 if summary['scan_complete'] is True and summary['secret_count'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
