import sqlite3

db = sqlite3.connect('storage/app.db')
db.row_factory = sqlite3.Row

tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t['name'] for t in tables])

print('\n=== Documents ===')
for row in db.execute('SELECT id, tenant_id, status, chunk_count, file_path FROM documents'):
    print(dict(row))

print('\n=== IngestJobs ===')
for row in db.execute('SELECT id, document_id, status, lease_owner FROM ingest_jobs ORDER BY id DESC LIMIT 10'):
    print(dict(row))

db.close()
