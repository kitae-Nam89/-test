# check_db.py
import sqlite3

DB_PATH = "writer_test.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 최근 5개만 확인
cur.execute("""
    SELECT id, name, birth_year, phone_last4, title, char_count, status, submitted_at
    FROM writer_tests
    ORDER BY id DESC
    LIMIT 5
""")

rows = cur.fetchall()

print("===== 최근 제출된 TEST 5건 =====")
for row in rows:
    print(row)

conn.close()
