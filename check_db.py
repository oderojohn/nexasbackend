import sqlite3
conn = sqlite3.connect(r'C:\Users\SERVER\Desktop\sms\backend\pos.sqlite3')
cur = conn.cursor()

# Check migration history
cur.execute("SELECT * FROM django_migrations WHERE app='pos' ORDER BY applied")
print("=== POS migrations ===")
for row in cur.fetchall():
    print(f"  {row[0]}-{row[1]}  app={row[2]}  applied={row[3]}")

# Check if pos_supplier really exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pos_supplier'")
result = cur.fetchone()
print(f"\npos_supplier table exists: {result is not None}")

# List ALL tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print("\n=== All tables ===")
for row in cur.fetchall():
    print(f"  {row[0]}")

conn.close()
