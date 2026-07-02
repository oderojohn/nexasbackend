import sqlite3
for path in [r'C:\Users\SERVER\Desktop\sms\backend\pos.sqlite3', r'C:\Users\SERVER\Desktop\sms\backend\pos_backup.sqlite3']:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pos_supplier'")
    result = cur.fetchone()
    print(f"{path}: pos_supplier exists = {result is not None}")
    conn.close()
