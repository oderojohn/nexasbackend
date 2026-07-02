import sqlite3
conn = sqlite3.connect(r'C:\Users\SERVER\Desktop\sms\backend\pos.sqlite3')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pos_%' ORDER BY name")
for row in cur.fetchall():
    print(row[0])
conn.close()
