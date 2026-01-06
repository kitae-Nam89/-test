from flask import Flask, request, jsonify, send_from_directory, session, redirect, make_response
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import os
import csv
from io import StringIO

# 🔒 DB 경로
# - 기본값: 현재 폴더의 writer_test.db (로컬 테스트용)
# - Render에서는 환경변수 DB_PATH 를 /var/data/writer_test.db 로 설정해서
#   영구 디스크에 저장하도록 사용
DB_PATH = os.environ.get("DB_PATH", "writer_test.db")

# 디렉터리가 포함된 경로라면, 없을 경우 자동 생성
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

# 🔐 관리자 비밀번호 / 세션 키 (환경변수 기반)
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "01045343815nam")  # 원하는 값으로 변경 가능

# static 폴더에 있는 html을 그대로 서빙
app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = SECRET_KEY
CORS(app, resources={r"/api/*": {"origins": "*"}})


# 👉 서버 켜면 제일 먼저 뜨는 프런트 UI (응시자용)
@app.route("/")
def index():
    # static 폴더 안의 "프리랜서 전체진행.html"을 메인 화면으로 사용
    return send_from_directory(app.static_folder, "프리랜서 전체진행.html")


# 🔐 관리자 세션 체크 데코레이터
def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"ok": False, "reason": "admin_only"}), 403
        return f(*args, **kwargs)
    return wrapper


# 🔐 관리자 로그인 페이지 (비밀번호 입력 화면)
@app.route("/admin_login", methods=["GET"])
def admin_login_page():
    # static/admin_login.html 서빙
    return send_from_directory(app.static_folder, "admin_login.html")


# 🔐 관리자 로그인 API (비밀번호 검증)
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(force=True)
    password = (data.get("password") or "").strip()

    if password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"ok": True})
    else:
        return jsonify({"ok": False, "reason": "wrong_password"}), 401


# 🔐 관리자 로그아웃
@app.route("/api/admin/logout", methods=["POST"])
@require_admin
def api_admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


# 🔐 관리자 페이지 진입 (관리자 UI)
@app.route("/admin", methods=["GET"])
def admin_page():
    if not session.get("is_admin"):
        # 로그인 안 되어 있으면 로그인 페이지로
        return redirect("/admin_login")
    # 로그인 되어 있으면 관리자 페이지 HTML 제공
    return send_from_directory(app.static_folder, "admin_test.html")


# 🚫 관리자 HTML 직접 접근 차단 (루트 경로: /admin_test.html)
@app.route("/admin_test.html")
def block_admin_html_root():
    return redirect("/admin_login")


# 🚫 관리자 HTML 직접 접근 차단 (정적 경로: /static/admin_test.html)
@app.route("/static/admin_test.html")
def block_admin_html_static():
    return redirect("/admin_login")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # 설정 테이블 (test_open 등)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    # 지원자 / TEST 테이블
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS writer_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            birth_year TEXT NOT NULL,
            phone_last4 TEXT NOT NULL,
            title TEXT,
            body TEXT,
            char_count INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', -- pending | pass | fail | return
            created_at TEXT NOT NULL,
            submitted_at TEXT,
            deadline_at TEXT NOT NULL
        )
        """
    )

    # 블랙리스트 테이블
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            birth_year TEXT NOT NULL,
            phone_last4 TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # 기본값: TEST 열려 있음
    cur.execute(
        "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
        ("test_open", "1"),
    )

    conn.commit()
    conn.close()


def is_blacklisted(name, birth_year, phone_last4):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM blacklist
        WHERE name=? AND birth_year=? AND phone_last4=?
        LIMIT 1
        """,
        (name, birth_year, phone_last4),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def get_test_open():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM config WHERE key='test_open'")
    row = cur.fetchone()
    conn.close()
    if not row:
        return True
    return row["value"] == "1"


def set_test_open(flag: bool):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("test_open", "1" if flag else "0"),
    )
    conn.commit()
    conn.close()

def export_writer_tests_csv():
    """
    writer_tests 전체 내용을 CSV 문자열로 반환.
    - 관리자 페이지에서 다운로드하여 PC에 보관용
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM writer_tests ORDER BY id ASC")
    rows = cur.fetchall()

    # 컬럼명 추출
    columns = [d[0] for d in cur.description]

    output = StringIO()
    writer = csv.writer(output)

    # 헤더
    writer.writerow(columns)

    # 데이터
    for r in rows:
        writer.writerow([r[col] for col in columns])

    conn.close()
    return output.getvalue()


def reset_writer_tests():
    """
    writer_tests 내용만 모두 삭제 (DB 파일 삭제 X, 구조 유지)
    - test 진행 중에는 호출하면 안 되며,
      반드시 test_open 이 0(종료)일 때만 사용해야 함.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM writer_tests")
    conn.commit()
    conn.close()


# ─────────────────────────
# 1) 관리자/응시 공통: TEST 오픈 상태
# ─────────────────────────
@app.route("/api/writer-test/config", methods=["GET"])
def api_config():
    return jsonify({"test_open": get_test_open()})


@app.route("/api/writer-test/set_open_flag", methods=["POST"])
@require_admin
def api_set_open_flag():
    data = request.get_json(force=True)
    flag = bool(data.get("test_open", True))
    set_test_open(flag)
    return jsonify({"ok": True, "test_open": flag})


# ─────────────────────────
# 2) 응시자: TEST 시작 전 등록 (이름/연도/뒷자리)
# ─────────────────────────
@app.route("/api/writer-test/register", methods=["POST"])
def api_register():
    """
    지원자 정보 입력 후 TEST 시작할 때 호출.
    - 블랙리스트 확인
    - 동일인 기록이 있으면 해당 test_id 리턴(재접속/재작성 가능)
    - 없으면 새 row 생성 후 test_id 리턴
    """
    if not get_test_open():
        return jsonify({"ok": False, "reason": "closed"}), 400

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    birth_year = (data.get("birthYear") or "").strip()
    phone_last4 = (data.get("phoneLast4") or "").strip()

    if not (name and birth_year and phone_last4):
        return jsonify({"ok": False, "reason": "invalid_input"}), 400

    if is_blacklisted(name, birth_year, phone_last4):
        return jsonify({"ok": False, "reason": "blacklisted"}), 403

    # 단순 현재 시각(서버 시간)만 기록, 타이머 로직 제거
    now = datetime.now()

    conn = get_db()
    cur = conn.cursor()

    # 동일인 기존 기록이 있으면 그걸 사용 (임시저장/반려 후 이어쓰기)
    cur.execute(
        """
        SELECT id, title, body, char_count, created_at, submitted_at, deadline_at, status
        FROM writer_tests
        WHERE name=? AND birth_year=? AND phone_last4=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (name, birth_year, phone_last4),
    )
    row = cur.fetchone()

    if row:
        test_id = row["id"]
        conn.close()
        return jsonify(
            {
                "ok": True,
                "testId": test_id,
                "name": name,
                "birthYear": birth_year,
                "phoneLast4": phone_last4,
                "title": row["title"],
                "body": row["body"],
                "charCount": row["char_count"],
                "status": row["status"],
                "deadlineAt": row["deadline_at"],
                "createdAt": row["created_at"],
                "submittedAt": row["submitted_at"],
            }
        )

    # 새로 생성: created_at만 의미 있게 사용, deadline_at은 빈 문자열로 저장
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    deadline_at = ""  # 타이머 사용 안 하므로 표시용만 남김

    cur.execute(
        """
        INSERT INTO writer_tests (name, birth_year, phone_last4, title, body, char_count,
                                  status, created_at, deadline_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, birth_year, phone_last4, "", "", 0, "pending", created_at, deadline_at),
    )
    test_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify(
        {
            "ok": True,
            "testId": test_id,
            "name": name,
            "birthYear": birth_year,
            "phoneLast4": phone_last4,
            "title": "",
            "body": "",
            "charCount": 0,
            "status": "pending",
            "deadlineAt": deadline_at,
            "createdAt": created_at,
            "submittedAt": None,
        }
    )

# ─────────────────────────
# 3) 응시자: 중간 저장 (임시저장)
# ─────────────────────────
@app.route("/api/writer-test/save_draft", methods=["POST"])
def api_save_draft():
    data = request.get_json(force=True)
    test_id = data.get("testId")
    title = (data.get("title") or "").strip()
    body = data.get("body") or ""

    if not test_id:
        return jsonify({"ok": False, "reason": "no_test_id"}), 400

    # 공백 제외 글자 수
    non_ws_body = (body or "").replace(" ", "").replace("\n", "").replace("\t", "")
    char_count = len(non_ws_body)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE writer_tests
        SET title=?, body=?, char_count=?
        WHERE id=?
        """,
        (title, body, char_count, test_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "charCount": char_count})


# ─────────────────────────
# 4) 응시자: 최종 제출
# ─────────────────────────
MIN_NON_WS_LENGTH = 2000  # 공백 제외 최소 글자 수


@app.route("/api/writer-test/submit", methods=["POST"])
def api_submit():
    data = request.get_json(force=True)
    test_id = data.get("testId")
    title = (data.get("title") or "").strip()
    body = data.get("body") or ""

    if not test_id:
        return jsonify({"ok": False, "reason": "no_test_id"}), 400

    # 공백 제외 글자 수
    non_ws_body = (body or "").replace(" ", "").replace("\n", "").replace("\t", "")
    char_count = len(non_ws_body)

    if char_count < MIN_NON_WS_LENGTH:
        return jsonify(
            {
                "ok": False,
                "reason": "too_short",
                "charCount": char_count,
                "minRequired": MIN_NON_WS_LENGTH,
            }
        ), 400

    # 현재 시각 (타이머와 무관, 단순 제출 시각 기록용)
    now = datetime.now()

    conn = get_db()
    cur = conn.cursor()

    # deadline_at은 더 이상 비교하지 않으므로 조회/검사 생략
    submitted_at = now.strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE writer_tests
        SET title=?, body=?, char_count=?, submitted_at=?
        WHERE id=?
        """,
        (title, body, char_count, submitted_at, test_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "submittedAt": submitted_at, "charCount": char_count})


# ─────────────────────────
# 5) 응시자: 결과 조회
# ─────────────────────────
@app.route("/api/writer-test/result", methods=["GET"])
def api_result():
    test_id = request.args.get("testId", type=int)
    if not test_id:
        return jsonify({"ok": False, "reason": "no_test_id"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, birth_year, phone_last4, title, char_count,
               status, created_at, submitted_at, deadline_at
        FROM writer_tests
        WHERE id=?
        """,
        (test_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404

    return jsonify(
        {
            "ok": True,
            "testId": row["id"],
            "name": row["name"],
            "birthYear": row["birth_year"],
            "phoneLast4": row["phone_last4"],
            "title": row["title"],
            "charCount": row["char_count"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "submittedAt": row["submitted_at"],
            "deadlineAt": row["deadline_at"],
        }
    )


# ─────────────────────────
# 6) 관리자: 지원자 목록
# ─────────────────────────
@app.route("/api/writer-test/list", methods=["GET"])
@require_admin
def api_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, birth_year, phone_last4, title, char_count,
               status, created_at, submitted_at, deadline_at
        FROM writer_tests
        ORDER BY id DESC
        """
    )
    rows = cur.fetchall()
    conn.close()

    tests = []
    for r in rows:
        tests.append(
            {
                "id": r["id"],
                "name": r["name"],
                "birthYear": r["birth_year"],
                "phoneLast4": r["phone_last4"],
                "title": r["title"],
                "length": r["char_count"],
                "status": r["status"],
                "createdAt": r["created_at"],
                "submittedAt": r["submitted_at"],
                "deadlineAt": r["deadline_at"],
            }
        )
    return jsonify({"tests": tests})


# ─────────────────────────
# 6-1) 관리자: 개별 TEST 본문 보기
# ─────────────────────────
@app.route("/api/writer-test/get", methods=["GET"])
@require_admin
def api_get_test():
    """
    관리자/응시자 공용: testId(또는 id)로 본문 포함 상세 조회
    """
    test_id = request.args.get("id", type=int) or request.args.get("testId", type=int)
    if not test_id:
        return jsonify({"ok": False, "error": "no_id"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, birth_year, phone_last4, title, body, char_count,
               status, created_at, submitted_at, deadline_at
        FROM writer_tests
        WHERE id=?
        """,
        (test_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"ok": False, "error": "not_found"}), 404

    test = {
        "id": row["id"],
        "name": row["name"],
        "birthYear": row["birth_year"],
        "phoneLast4": row["phone_last4"],
        "title": row["title"],
        "content": row["body"],  # 관리자 페이지 viewer에서 content로 사용
        "charCount": row["char_count"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "submittedAt": row["submitted_at"],
        "deadlineAt": row["deadline_at"],
    }
    return jsonify({"ok": True, "test": test})


# ─────────────────────────
# 7) 관리자: 블랙리스트 목록
# ─────────────────────────
@app.route("/api/writer-test/blacklist", methods=["GET"])
@require_admin
def api_blacklist_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT name, birth_year, phone_last4, reason, created_at
        FROM blacklist
        ORDER BY id DESC
        """
    )
    rows = cur.fetchall()
    conn.close()

    bl = []
    for r in rows:
        bl.append(
            {
                "name": r["name"],
                "birthYear": r["birth_year"],
                "phoneLast4": r["phone_last4"],
                "reason": r["reason"],
                "createdAt": r["created_at"],
            }
        )

    return jsonify({"blacklist": bl})


# ─────────────────────────
# 8) 관리자: 상태 변경 (합격/불합격/반려/대기)
# ─────────────────────────
@app.route("/api/writer-test/update_status", methods=["POST"])
@require_admin
def api_update_status():
    data = request.get_json(force=True)
    test_id = data.get("id")
    new_status = data.get("status")

    # ★ 여기서 return(반려) 허용
    valid_statuses = ("pending", "pass", "fail", "return")
    if not test_id or new_status not in valid_statuses:
        return jsonify({"ok": False, "reason": "invalid_input"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE writer_tests SET status=? WHERE id=?",
        (new_status, test_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})

# ─────────────────────────
# 8-1) 관리자: 전체 백업 + 초기화 (TEST 종료용)
# ─────────────────────────
@app.route("/api/writer-test/export_and_reset", methods=["GET"])
@require_admin
def api_export_and_reset():
    """
    [안전 정책]
    - config.test_open 이 '0'(닫힘)일 때만 동작.
    - 1) writer_tests 전체를 CSV로 만들어 응답(다운로드)
    - 2) 그 뒤 writer_tests 내용을 전부 삭제(reset)
    """
    # TEST가 열린 상태에서는 백업/초기화 금지
    if get_test_open():
        return jsonify({"ok": False, "reason": "test_open"}), 400

    # 1) CSV 백업
    csv_data = export_writer_tests_csv()

    # 2) 내용 초기화 (DB 파일은 유지)
    reset_writer_tests()

    # 3) 브라우저에서 자동 다운로드 되도록 응답
    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=writer_tests_backup.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response

# ─────────────────────────
# 9) 관리자: 개별 삭제 / 전체 삭제
# ─────────────────────────
@app.route("/api/writer-test/delete", methods=["POST"])
@require_admin
def api_delete():
    data = request.get_json(force=True)
    test_id = data.get("id")
    if not test_id:
        return jsonify({"ok": False, "reason": "invalid_input"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM writer_tests WHERE id=?", (test_id,))
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/writer-test/delete_all", methods=["POST"])
@require_admin
def api_delete_all():
    """
    전체 삭제는 TEST가 닫힌 상태에서만 허용.
    (테스트 진행 중 실수로 전체삭제 방지)
    """
    if get_test_open():
        return jsonify({"ok": False, "reason": "test_open"}), 400

    reset_writer_tests()
    return jsonify({"ok": True})



# ─────────────────────────
# 10) 관리자: 블랙리스트 추가/삭제
# ─────────────────────────
@app.route("/api/writer-test/blacklist_add", methods=["POST"])
@require_admin
def api_blacklist_add():
    data = request.get_json(force=True)

    test_id = data.get("id")
    reason = (data.get("reason") or "").strip()

    if test_id:
        # test_id 기준으로 지원자 정보 가져와서 등록
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, birth_year, phone_last4 FROM writer_tests
            WHERE id=?
            """,
            (test_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"ok": False, "reason": "not_found"}), 404

        name = row["name"]
        birth_year = row["birth_year"]
        phone_last4 = row["phone_last4"]
    else:
        name = (data.get("name") or "").strip()
        birth_year = (data.get("birthYear") or "").strip()
        phone_last4 = (data.get("phoneLast4") or "").strip()

    if not (name and birth_year and phone_last4):
        return jsonify({"ok": False, "reason": "invalid_input"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO blacklist (name, birth_year, phone_last4, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, birth_year, phone_last4, reason, datetime.now().strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/api/writer-test/blacklist_remove", methods=["POST"])
@require_admin
def api_blacklist_remove():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    birth_year = (data.get("birthYear") or "").strip()
    phone_last4 = (data.get("phoneLast4") or "").strip()

    if not (name and birth_year and phone_last4):
        return jsonify({"ok": False, "reason": "invalid_input"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM blacklist
        WHERE name=? AND birth_year=? AND phone_last4=?
        """,
        (name, birth_year, phone_last4),
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
