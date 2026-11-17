"""Synthetic trusted adapter: actual JSON file writes/reads in the scratch cwd."""
import json
from pathlib import Path
import sys

store = Path('store.json')
store.write_text('{}', encoding='utf8')
results = []
for step in json.load(sys.stdin)['operations']:
    data = json.loads(store.read_text(encoding='utf8'))
    if step['op'] == 'put':
        data[step['key']] = step['value']
        store.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        results.append(None)
    elif step['op'] == 'get':
        results.append(data.get(step['key']))
    elif step['op'] == 'keys':
        results.append(sorted(data))
    else:
        raise ValueError('Unsupported operation')
print(json.dumps(results, ensure_ascii=False))
