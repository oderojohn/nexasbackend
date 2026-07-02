import sqlite3
conn = sqlite3.connect(r'C:\Users\SERVER\Desktop\sms\backend\pos.sqlite3')
cur = conn.cursor()
cur.execute("PRAGMA table_info(pos_supplier)")
cols = cur.fetchall()
print("pos_supplier columns:")
for c in cols:
    print(f"  {c}")
conn.close()
