"""Synthetic trusted replacement: actual SQLite transactions in the scratch cwd."""
import json
import sqlite3
import sys
from contextlib import closing

results = []
with closing(sqlite3.connect('store.sqlite')) as db:
    db.execute('CREATE TABLE entries (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    for step in json.load(sys.stdin)['operations']:
        if step['op'] == 'put':
            db.execute('INSERT INTO entries VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (step['key'], json.dumps(step['value'], ensure_ascii=False)))
            db.commit()
            results.append(None)
        elif step['op'] == 'get':
            row = db.execute('SELECT value FROM entries WHERE key=?', (step['key'],)).fetchone()
            results.append(json.loads(row[0]) if row else None)
        elif step['op'] == 'keys':
            results.append(sorted(row[0] for row in db.execute('SELECT key FROM entries')))
        else:
            raise ValueError('Unsupported operation')
print(json.dumps(results, ensure_ascii=False))
