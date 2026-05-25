import sqlite3, json
conn = sqlite3.connect('licencas.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
tables = ['admin_users','customers','products','licenses']
data = {}
for t in tables:
    rows = cur.execute(f'select * from {t}').fetchall()
    data[t] = [dict(r) for r in rows]
print(json.dumps(data, ensure_ascii=False))
