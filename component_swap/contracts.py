"""Execute explicitly trusted Python adapters against bounded, synthetic contracts.
Not a sandbox. A fresh working directory is a fixture boundary, not isolation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from .core import Invalid, canonical, identifier, parse, plan, read

OUTPUT_LIMIT = 16384
SCRIPT_LIMIT = 131072
FILES = {'inventory.json', 'replacements.json', 'contract.json', 'baseline.py',
         'candidate.py', 'observations.json', 'report.json', 'review.md'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def contract(raw, planning):
    spec = parse(raw)
    if not isinstance(spec, dict) or set(spec) != {'schema', 'slot', 'timeout_ms', 'cases'}:
        raise Invalid('Invalid contract fields.')
    if type(spec['schema']) is not int or spec['schema'] != 1:
        raise Invalid('Unsupported contract schema.')
    identifier(spec['slot'])
    if spec['slot'] not in planning['changed_components']:
        raise Invalid('Contract must bind an actually changed component slot.')
    if type(spec['timeout_ms']) is not int or not 100 <= spec['timeout_ms'] <= 10000:
        raise Invalid('Timeout must be 100..10000 milliseconds.')
    if not isinstance(spec['cases'], list) or not 1 <= len(spec['cases']) <= 20:
        raise Invalid('Expected 1..20 contract cases.')
    seen = set()
    for case in spec['cases']:
        if not isinstance(case, dict) or set(case) != {'id', 'input', 'expected'}:
            raise Invalid('Each case requires id, input, expected.')
        identifier(case['id'])
        if case['id'] in seen:
            raise Invalid('Duplicate case id.')
        seen.add(case['id'])
        if len(canonical(case)) > OUTPUT_LIMIT:
            raise Invalid('Case exceeds 16 KiB.')
    return spec


def execute(script, request, timeout_ms):
    """One process per case, no shell, no inherited cwd/import path or env secrets.
    Trusted code still has the caller's OS privileges. Children are unsupported.
    """
    with tempfile.TemporaryDirectory(prefix='component-contract-') as folder:
        script_path = Path(folder) / 'adapter.py'
        script_path.write_bytes(script)
        # -I ignores PYTHONPATH and user-site; do not forward user API credentials.
        env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        env['PYTHONIOENCODING'] = 'utf-8'
        started = time.monotonic()
        try:
            proc = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', str(script_path)], cwd=folder,
                                    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        except OSError:
            return {'execution': 'launch_error', 'returncode': None, 'stdout': '',
                    'stderr_sha256': digest(b''), 'stderr_bytes': 0, 'duration_ms': 0}
        data = {'stdout': bytearray(), 'stderr': bytearray()}
        exceeded = threading.Event()

        def collect(name, stream):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    remaining = OUTPUT_LIMIT - len(data[name])
                    data[name].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        exceeded.set()
                        try:
                            proc.kill()
                        except OSError:
                            pass
                        break
            finally:
                stream.close()

        def feed():
            try:
                proc.stdin.write(canonical(request))
                proc.stdin.close()
            except (OSError, ValueError):
                pass

        readers = [threading.Thread(target=collect, args=(name, getattr(proc, name)), daemon=True)
                   for name in ('stdout', 'stderr')]
        for thread in readers:
            thread.start()
        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        execution = 'completed'
        try:
            proc.wait(timeout=timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            execution = 'timeout'
            proc.kill()
            proc.wait()
        for thread in readers + [writer]:
            thread.join(timeout=0.25)
        if any(thread.is_alive() for thread in readers + [writer]):
            execution = 'open_streams'
        elif exceeded.is_set():
            execution = 'output_limit'
        raw = bytes(data['stdout'])
        # Preserve arbitrary output exactly without trusting UTF-8 or JSON.
        import base64
        return {'execution': execution, 'returncode': proc.returncode,
                'stdout': base64.b64encode(raw).decode('ascii'),
                'stderr_sha256': digest(bytes(data['stderr'])), 'stderr_bytes': len(data['stderr']),
                'duration_ms': int((time.monotonic() - started) * 1000)}


def outcome(record, expected):
    import base64
    if not isinstance(record, dict) or set(record) != {'execution', 'returncode', 'stdout', 'stderr_sha256', 'stderr_bytes', 'duration_ms'}:
        raise Invalid('Malformed execution evidence.')
    if record['execution'] not in {'completed', 'timeout', 'output_limit', 'open_streams', 'launch_error'}:
        raise Invalid('Unknown execution result.')
    if record['returncode'] is not None and type(record['returncode']) is not int:
        raise Invalid('Invalid return code.')
    if any(type(record[k]) is not int or record[k] < 0 for k in ('duration_ms', 'stderr_bytes')):
        raise Invalid('Invalid execution counters.')
    if record['stderr_bytes'] > OUTPUT_LIMIT:
        raise Invalid('Oversized stderr evidence.')
    import re
    if not isinstance(record['stderr_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', record['stderr_sha256']):
        raise Invalid('Invalid stderr hash.')
    try:
        raw = base64.b64decode(record['stdout'], validate=True)
    except (ValueError, TypeError):
        raise Invalid('Invalid stdout encoding.') from None
    if len(raw) > OUTPUT_LIMIT:
        raise Invalid('Oversized stdout.')
    if record['execution'] != 'completed':
        return record['execution']
    if record['returncode'] != 0:
        return 'process_error'
    try:
        value = parse(raw)
    except Invalid:
        return 'invalid_output'
    return 'passed' if canonical(value) == canonical(expected) else 'mismatch'


def summarize(raws, evidence):
    planning = plan(raws['inventory.json'], raws['replacements.json'])
    spec = contract(raws['contract.json'], planning)
    if not isinstance(evidence, dict) or set(evidence) != {'schema', 'input_sha256', 'rows'} or type(evidence['schema']) is not int or evidence['schema'] != 1:
        raise Invalid('Invalid evidence schema.')
    if evidence['input_sha256'] != {k: digest(v) for k, v in raws.items()}:
        raise Invalid('Evidence input binding mismatch.')
    expected_keys = [(c['id'], adapter) for c in spec['cases'] for adapter in ('baseline', 'candidate')]
    if not isinstance(evidence['rows'], list) or len(evidence['rows']) != len(expected_keys):
        raise Invalid('Incomplete evidence.')
    outcomes = {}
    for row, key in zip(evidence['rows'], expected_keys):
        if not isinstance(row, dict) or set(row) != {'case', 'adapter', 'record'} or (row['case'], row['adapter']) != key:
            raise Invalid('Reordered or duplicated evidence.')
        case = next(c for c in spec['cases'] if c['id'] == key[0])
        outcomes[key] = outcome(row['record'], case['expected'])
    rows = []
    for case in spec['cases']:
        a, b = (outcomes[(case['id'], role)] for role in ('baseline', 'candidate'))
        if a == b == 'passed':
            change = 'both_satisfy_contract'
        elif a == 'passed' and b == 'mismatch':
            change = 'regression'
        elif a == 'mismatch' and b == 'passed':
            change = 'candidate_resolves_case'
        elif b == 'passed':
            change = 'candidate_passed_baseline_not_verified'
        elif a == 'passed':
            change = 'candidate_execution_or_protocol_failed'
        else:
            change = 'neither_satisfies_contract'
        rows.append({'case': case['id'], 'baseline': a, 'candidate': b, 'change': change})
    return {'schema': 1, 'slot': spec['slot'], 'input_sha256': evidence['input_sha256'],
            'evidence_sha256': digest(canonical(evidence)),
            'declaration_status': planning['proposed_status'], 'affected_components': planning['affected_components'],
            'comparison_complete': all(v in {'passed', 'mismatch'} for v in outcomes.values()),
            'candidate_all_passed': all(r['candidate'] == 'passed' for r in rows),
            'baseline_all_passed': all(r['baseline'] == 'passed' for r in rows), 'cases': rows,
            'manual_review_required': True,
            'limits': ['Trusted code only; not a security sandbox.',
                       'Only explicit supplied cases and exact typed JSON outputs were checked.',
                       'Fresh per-case processes do not prove migration, rollback, service reliability or production safety.',
                       'Evidence consistency is not authenticated execution; replay requires a new run.',
                       'Adapter children/background processes are unsupported; time/output limits govern the direct adapter.',
                       'Inputs, adapter source and stdout are retained and may be sensitive. Stderr is truncated and hashed only.']}


def review(report):
    safe = canonical(report).decode().replace('`', '\\u0060').replace('<', '\\u003c').replace('>', '\\u003e')
    return ('# Observed component contract review\n\nNot production approval. Review baseline failures separately from regressions.\n\n```json\n' + safe + '```\n').encode()


def run(inventory, replacements, contract_path, baseline, candidate, out, trusted=False):
    if trusted is not True:
        raise Invalid('Explicit --trust-adapters is required: arbitrary local code, not a sandbox.')
    root = Path(out)
    if root.exists() or root.is_symlink() or not root.parent.is_dir():
        raise Invalid('Output must be a new directory beneath an existing parent.')
    paths = {'inventory.json': inventory, 'replacements.json': replacements,
             'contract.json': contract_path, 'baseline.py': baseline, 'candidate.py': candidate}
    raws = {name: read(p, SCRIPT_LIMIT if name.endswith('.py') else 2*1024*1024) for name, p in paths.items()}
    spec = contract(raws['contract.json'], plan(raws['inventory.json'], raws['replacements.json']))
    evidence = {'schema': 1, 'input_sha256': {k: digest(v) for k, v in raws.items()}, 'rows': []}
    for case in spec['cases']:
        for adapter in ('baseline', 'candidate'):
            evidence['rows'].append({'case': case['id'], 'adapter': adapter,
                                     'record': execute(raws[adapter + '.py'], case['input'], spec['timeout_ms'])})
    report = summarize(raws, evidence)
    outputs = {**raws, 'observations.json': canonical(evidence), 'report.json': canonical(report), 'review.md': review(report)}
    root.mkdir(exist_ok=False)
    for name, raw in outputs.items():
        (root / name).write_bytes(raw)
    return report


def verify(folder):
    root = Path(folder)
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()} != FILES:
        raise Invalid('Unexpected contract bundle layout.')
    raws = {k: read(root / k, SCRIPT_LIMIT if k.endswith('.py') else 2*1024*1024)
            for k in ('inventory.json', 'replacements.json', 'contract.json', 'baseline.py', 'candidate.py')}
    evidence_raw = read(root / 'observations.json')
    evidence = parse(evidence_raw)
    if evidence_raw != canonical(evidence):
        raise Invalid('Execution evidence bytes are not canonical.')
    report = summarize(raws, evidence)
    if read(root / 'report.json') != canonical(report) or read(root / 'review.md') != review(report):
        raise Invalid('Contract report differs from recomputation.')
    return {'verified': True, 'candidate_all_passed': report['candidate_all_passed'],
            'comparison_complete': report['comparison_complete'],
            'note': 'Internal consistency only; adapters were NOT re-executed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run')
    for field in ('inventory', 'replacements', 'contract', 'baseline', 'candidate'):
        p.add_argument(field)
    p.add_argument('--out', required=True)
    p.add_argument('--trust-adapters', action='store_true')
    p = sub.add_parser('verify')
    p.add_argument('bundle')
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            report = verify(args.bundle)
        else:
            report = run(args.inventory, args.replacements, args.contract, args.baseline, args.candidate, args.out, args.trust_adapters)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report['comparison_complete']:
            return 2
        return 0 if report.get('candidate_all_passed') else 1
    except (Invalid, OSError, TypeError, ValueError, RecursionError):
        print('Contract input, execution or bundle validation failed; private values are not echoed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
