# -*- coding: utf-8 -*-
"""SQLite 数据层（v2）。

表结构对应方案书「核心数据模型」，并在 v2 中补齐：
  - 课程级参数（班级 / 教材 / 自动续跑 / 续跑文件类型）
  - 资料去重与原地更新（不再重复插入导致知识库膨胀）
  - 产物修改历史（artifact_revisions，支持查看与回退）
  - 后台任务持久化（workflow_tasks，重启后不会「假运行」）
  - 公共资源区（vault_items）与索引

并发说明：FastAPI 主线程 + 后台生成线程都会访问，用全局可重入锁 + 每次短连接保证安全，
并开启 WAL、busy_timeout 与外键约束。
"""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from . import config

_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS courses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  semester TEXT DEFAULT '',
  weeks INT DEFAULT 16,
  theme TEXT DEFAULT '',
  class_name TEXT DEFAULT '',
  textbook TEXT DEFAULT '',
  status TEXT DEFAULT 'created',
  auto_chain INT DEFAULT 1,
  auto_types TEXT DEFAULT '["lesson_plan","handout","courseware","script"]',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS materials(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INT NOT NULL,
  filename TEXT DEFAULT '',
  content TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  hash TEXT DEFAULT '',
  chars INT DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS week_plans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INT NOT NULL,
  week_no INT NOT NULL,
  title TEXT DEFAULT '',
  hours INT DEFAULT 2,
  objective TEXT DEFAULT '',
  ideo TEXT DEFAULT '',
  status TEXT DEFAULT 'review',
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS artifacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INT NOT NULL,
  week_no INT,
  file_type TEXT NOT NULL,
  title TEXT DEFAULT '',
  content TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  feedback TEXT DEFAULT '',
  warnings TEXT DEFAULT '',
  model TEXT DEFAULT '',
  tokens_in INT DEFAULT 0,
  tokens_out INT DEFAULT 0,
  cost REAL DEFAULT 0,
  latency_ms INT DEFAULT 0,
  word_count INT DEFAULT 0,
  revision INT DEFAULT 1,
  task_id TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS artifact_revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id INT NOT NULL,
  course_id INT NOT NULL,
  version INT DEFAULT 1,
  content TEXT DEFAULT '',
  feedback TEXT DEFAULT '',
  source TEXT DEFAULT 'generate',
  model TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS workflow_tasks(
  id TEXT PRIMARY KEY,
  course_id INT NOT NULL,
  kind TEXT DEFAULT 'generate',
  payload TEXT DEFAULT '{}',
  status TEXT DEFAULT 'queued',
  done INT DEFAULT 0,
  total INT DEFAULT 0,
  log TEXT DEFAULT '[]',
  message TEXT DEFAULT '',
  cancel INT DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS vault_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT DEFAULT 'materials',
  name TEXT NOT NULL,
  content TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  enabled INT DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT (datetime('now','localtime')),
  trace_id TEXT,
  model TEXT,
  task TEXT DEFAULT '',
  in_tokens INT DEFAULT 0,
  out_tokens INT DEFAULT 0,
  cost REAL DEFAULT 0,
  latency_ms INT DEFAULT 0,
  course_id INT,
  week_no INT,
  file_type TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS confirm_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT (datetime('now','localtime')),
  course_id INT,
  artifact_id INT,
  action TEXT,
  reason TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conversation(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INT,
  role TEXT,
  text TEXT,
  ts TEXT DEFAULT (datetime('now','localtime'))
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_materials_course ON materials(course_id, id);
CREATE INDEX IF NOT EXISTS ix_week_plans_course ON week_plans(course_id, week_no);
CREATE INDEX IF NOT EXISTS ix_artifacts_course ON artifacts(course_id, week_no, file_type);
CREATE INDEX IF NOT EXISTS ix_revisions_artifact ON artifact_revisions(artifact_id, id);
CREATE INDEX IF NOT EXISTS ix_tasks_course ON workflow_tasks(course_id, created_at);
CREATE INDEX IF NOT EXISTS ix_usage_course ON usage(course_id, id);
CREATE INDEX IF NOT EXISTS ix_usage_ts ON usage(ts);
CREATE INDEX IF NOT EXISTS ix_confirm_course ON confirm_log(course_id, id);
CREATE INDEX IF NOT EXISTS ix_conversation_course ON conversation(course_id, id);
CREATE INDEX IF NOT EXISTS ix_vault_kind ON vault_items(kind, enabled);
"""

# v1 → v2 的增量列（SQLite 不支持 IF NOT EXISTS，用 PRAGMA 探测）
_MIGRATIONS = {
    "courses": {
        "class_name": "TEXT DEFAULT ''",
        "textbook": "TEXT DEFAULT ''",
        "auto_chain": "INT DEFAULT 1",
        "auto_types": "TEXT DEFAULT '[\"lesson_plan\",\"handout\",\"courseware\",\"script\"]'",
        "updated_at": "TEXT DEFAULT ''",
    },
    "materials": {
        "hash": "TEXT DEFAULT ''",
        "chars": "INT DEFAULT 0",
        "updated_at": "TEXT DEFAULT ''",
    },
    "week_plans": {"updated_at": "TEXT DEFAULT ''"},
    "artifacts": {
        "warnings": "TEXT DEFAULT ''",
        "latency_ms": "INT DEFAULT 0",
        "word_count": "INT DEFAULT 0",
        "revision": "INT DEFAULT 1",
        "task_id": "TEXT DEFAULT ''",
    },
    "usage": {
        "task": "TEXT DEFAULT ''",
        "latency_ms": "INT DEFAULT 0",
    },
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _db():
    """短连接上下文：自动提交/回滚，统一加锁。"""
    with _LOCK:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=8000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _rows(rows):
    return [dict(r) for r in rows]


def _add_missing_columns(conn):
    for table, cols in _MIGRATIONS.items():
        try:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue
        for col, ddl in cols.items():
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                except sqlite3.Error:
                    pass


def init():
    """建表 + 迁移 + 索引 + 恢复中断任务 + 种子公共资源区（幂等）。"""
    with _db() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        conn.executescript(_SCHEMA)
        _add_missing_columns(conn)
        conn.executescript(_INDEXES)
        # 同一课程 + 周次 + 类型只允许一条产物（老库若有重复则跳过）
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_artifacts_unique "
                "ON artifacts(course_id, week_no, file_type)")
        except sqlite3.Error:
            pass
        conn.execute(
            "UPDATE workflow_tasks SET status='interrupted', message='服务重启，任务已中断' "
            "WHERE status IN ('queued','running')")
        conn.execute(
            "UPDATE courses SET auto_types=? WHERE COALESCE(auto_types,'') IN ('', ?)",
            ('["lesson_plan","handout","courseware","script"]',
             '["lesson_plan","handout","script"]'))
        conn.execute("UPDATE courses SET updated_at=? WHERE COALESCE(updated_at,'')=''", (_now(),))
    _seed_vault()


# ================= 课程 =================
def create_course(name, semester, weeks, theme, class_name="", textbook="") -> int:
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO courses(name,semester,weeks,theme,class_name,textbook,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (name, semester, int(weeks), theme, class_name, textbook, _now()))
        return cur.lastrowid


def _course_stats_sql(where=""):
    return f"""
    SELECT c.*,
      (SELECT COUNT(*) FROM materials m WHERE m.course_id=c.id) AS material_cnt,
      (SELECT COUNT(*) FROM week_plans p WHERE p.course_id=c.id) AS planned_weeks,
      (SELECT COUNT(*) FROM week_plans p WHERE p.course_id=c.id AND p.status='approved') AS approved_weeks,
      (SELECT COUNT(*) FROM artifacts a WHERE a.course_id=c.id) AS artifact_cnt,
      (SELECT COUNT(*) FROM artifacts a WHERE a.course_id=c.id AND a.status='approved') AS approved_artifacts,
      (SELECT COUNT(*) FROM artifacts a WHERE a.course_id=c.id AND a.status='review') AS review_artifacts,
      (SELECT COALESCE(SUM(cost),0) FROM usage u WHERE u.course_id=c.id) AS cost
    FROM courses c {where}
    """


def get_course(course_id) -> dict:
    with _db() as conn:
        r = conn.execute(_course_stats_sql("WHERE c.id=?"), (course_id,)).fetchone()
        return dict(r) if r else None


def list_courses() -> list:
    with _db() as conn:
        rows = conn.execute(_course_stats_sql("") + " ORDER BY c.id DESC").fetchall()
        return _rows(rows)


_COURSE_FIELDS = {"name", "semester", "weeks", "theme", "class_name", "textbook",
                  "status", "auto_chain", "auto_types"}


def update_course(course_id, **fields):
    sets, args = [], []
    for k, v in fields.items():
        if k in _COURSE_FIELDS and v is not None:
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k == "auto_types" and not isinstance(v, str) else v)
    if not sets:
        return
    sets.append("updated_at=?")
    args += [_now(), course_id]
    with _db() as conn:
        conn.execute(f"UPDATE courses SET {','.join(sets)} WHERE id=?", args)


def update_course_status(course_id, status):
    update_course(course_id, status=status)


def delete_course(course_id: int):
    with _db() as conn:
        for table in ("materials", "week_plans", "artifacts", "artifact_revisions",
                      "workflow_tasks", "usage", "confirm_log", "conversation"):
            conn.execute(f"DELETE FROM {table} WHERE course_id=?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id=?", (course_id,))


# ================= 资料 =================
def add_material(course_id, filename, content, summary="") -> tuple:
    """新增或更新同名资料，返回 (id, replaced)。避免重复「解析」把资料越堆越多。"""
    import hashlib
    content = (content or "")[: config.MAX_MATERIAL_CHARS]
    h = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
    with _db() as conn:
        old = conn.execute(
            "SELECT id,content,hash,summary FROM materials WHERE course_id=? AND filename=? "
            "ORDER BY id DESC LIMIT 1", (course_id, filename)).fetchone()
        if old:
            if old["hash"] == h and not summary:
                # 内容未变且未提供新摘要：保留原摘要，仅刷新时间
                conn.execute("UPDATE materials SET updated_at=? WHERE id=?", (_now(), old["id"]))
                return old["id"], True
            conn.execute(
                "UPDATE materials SET content=?, summary=?, hash=?, chars=?, updated_at=? WHERE id=?",
                (content, summary, h, len(content), _now(), old["id"]))
            return old["id"], True
        cur = conn.execute(
            "INSERT INTO materials(course_id,filename,content,summary,hash,chars) VALUES(?,?,?,?,?,?)",
            (course_id, filename, content, summary, h, len(content)))
        return cur.lastrowid, False


def get_material(material_id) -> dict:
    with _db() as conn:
        r = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        return dict(r) if r else None


def list_materials(course_id, with_content=False) -> list:
    cols = "*" if with_content else "id,course_id,filename,summary,hash,chars,created_at,updated_at"
    with _db() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM materials WHERE course_id=? ORDER BY id", (course_id,)).fetchall()
        return _rows(rows)


def update_material_summary(material_id, summary):
    with _db() as conn:
        conn.execute("UPDATE materials SET summary=?, updated_at=? WHERE id=?",
                     (summary or "", _now(), material_id))


def delete_material(material_id):
    with _db() as conn:
        conn.execute("DELETE FROM materials WHERE id=?", (material_id,))


def clear_materials(course_id):
    with _db() as conn:
        conn.execute("DELETE FROM materials WHERE course_id=?", (course_id,))


# ================= 周次规划（门 A） =================
def save_week_plans(course_id, plans: list) -> None:
    """整表覆盖写入（生成地图时用），status 默认 review。"""
    with _db() as conn:
        conn.execute("DELETE FROM week_plans WHERE course_id=?", (course_id,))
        conn.executemany(
            "INSERT INTO week_plans(course_id,week_no,title,hours,objective,ideo,status,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [(course_id, int(p.get("week") or p.get("week_no") or 0), p.get("title", ""),
              int(p.get("hours") or 2), p.get("objective", ""), p.get("ideo", ""),
              p.get("status", "review"), _now()) for p in plans if p.get("week") or p.get("week_no")])


def list_week_plans(course_id) -> list:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM week_plans WHERE course_id=? ORDER BY week_no", (course_id,)).fetchall()
        return _rows(rows)


def get_week_plan(course_id, week_no) -> dict:
    with _db() as conn:
        r = conn.execute("SELECT * FROM week_plans WHERE course_id=? AND week_no=?",
                         (course_id, week_no)).fetchone()
        return dict(r) if r else None


def update_week_plan(course_id, week_no, **fields):
    allowed = {"title", "hours", "objective", "ideo", "status"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            args.append(v)
    if not sets:
        return False
    sets.append("updated_at=?")
    args += [_now(), course_id, week_no]
    with _db() as conn:
        cur = conn.execute(
            f"UPDATE week_plans SET {','.join(sets)} WHERE course_id=? AND week_no=?", args)
        return cur.rowcount > 0


def approve_week_plans(course_id, weeks=None):
    with _db() as conn:
        if weeks:
            qs = ",".join("?" * len(weeks))
            conn.execute(
                f"UPDATE week_plans SET status='approved', updated_at=? "
                f"WHERE course_id=? AND week_no IN ({qs})",
                [_now(), course_id] + list(weeks))
        else:
            conn.execute("UPDATE week_plans SET status='approved', updated_at=? WHERE course_id=?",
                         (_now(), course_id))


def delete_week_plans(course_id):
    with _db() as conn:
        conn.execute("DELETE FROM week_plans WHERE course_id=?", (course_id,))


# ================= 产物（门 B） =================
def ensure_artifact(course_id, week_no, file_type) -> dict:
    """取或建一条产物记录（幂等），返回记录。"""
    with _db() as conn:
        r = conn.execute(
            "SELECT * FROM artifacts WHERE course_id=? AND week_no=? AND file_type=?",
            (course_id, week_no, file_type)).fetchone()
        if r:
            return dict(r)
        try:
            cur = conn.execute(
                "INSERT INTO artifacts(course_id,week_no,file_type,title,status) VALUES(?,?,?,?,?)",
                (course_id, week_no, file_type, f"week{week_no}-{file_type}", "pending"))
            rid = cur.lastrowid
        except sqlite3.IntegrityError:
            rid = conn.execute(
                "SELECT id FROM artifacts WHERE course_id=? AND week_no=? AND file_type=?",
                (course_id, week_no, file_type)).fetchone()["id"]
        r = conn.execute("SELECT * FROM artifacts WHERE id=?", (rid,)).fetchone()
        return dict(r)


def get_artifact(artifact_id) -> dict:
    with _db() as conn:
        r = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return dict(r) if r else None


_ARTIFACT_FIELDS = {"status", "content", "title", "model", "tokens_in", "tokens_out",
                    "cost", "feedback", "warnings", "latency_ms", "word_count", "revision",
                    "task_id"}


def set_artifact(artifact_id, *, tokens=None, bump_revision=False, **fields):
    sets, args = ["updated_at=?"], [_now()]
    for k, v in fields.items():
        if k in _ARTIFACT_FIELDS and v is not None:
            sets.append(f"{k}=?")
            args.append(v)
    if tokens is not None:
        sets += ["tokens_in=?", "tokens_out=?"]
        args += [tokens.get("in", 0), tokens.get("out", 0)]
    if bump_revision:
        sets.append("revision=COALESCE(revision,1)+1")
    args.append(artifact_id)
    with _db() as conn:
        conn.execute(f"UPDATE artifacts SET {','.join(sets)} WHERE id=?", args)


def list_artifacts(course_id, with_content=True) -> list:
    cols = "*" if with_content else (
        "id,course_id,week_no,file_type,title,status,feedback,warnings,model,"
        "tokens_in,tokens_out,cost,latency_ms,word_count,revision,created_at,updated_at")
    with _db() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM artifacts WHERE course_id=? ORDER BY week_no, id", (course_id,)).fetchall()
        return _rows(rows)


def artifacts_map(course_id) -> dict:
    return {f"{a['week_no']}-{a['file_type']}": a for a in list_artifacts(course_id, with_content=False)}


def delete_artifact(artifact_id):
    with _db() as conn:
        conn.execute("DELETE FROM artifact_revisions WHERE artifact_id=?", (artifact_id,))
        conn.execute("DELETE FROM artifacts WHERE id=?", (artifact_id,))


def approve_artifact(artifact_id):
    set_artifact(artifact_id, status="approved")


def reset_artifact(artifact_id, reason="重新生成"):
    a = get_artifact(artifact_id)
    if not a:
        return False
    if a.get("content"):
        save_revision(artifact_id, a["content"], feedback=reason, source="before_reset",
                      model=a.get("model", ""))
    set_artifact(artifact_id, status="pending", content="", feedback="", warnings="",
                 word_count=0, model="", tokens=None, cost=0, latency_ms=0)
    return True


# ================= 修改历史 =================
def save_revision(artifact_id, content, *, feedback="", source="generate", model="") -> int:
    a = get_artifact(artifact_id)
    if not a:
        return 0
    with _db() as conn:
        v = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM artifact_revisions WHERE artifact_id=?",
            (artifact_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO artifact_revisions(artifact_id,course_id,version,content,feedback,source,model) "
            "VALUES(?,?,?,?,?,?,?)",
            (artifact_id, a["course_id"], v, content or "", feedback or "", source, model or ""))
        conn.execute("UPDATE artifacts SET revision=?, updated_at=? WHERE id=?",
                     (v, _now(), artifact_id))
        return cur.lastrowid


def list_revisions(artifact_id, with_content=True) -> list:
    cols = "*" if with_content else "id,artifact_id,course_id,version,feedback,source,model,created_at,length(content) AS chars"
    with _db() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM artifact_revisions WHERE artifact_id=? ORDER BY version DESC",
            (artifact_id,)).fetchall()
        return _rows(rows)


def get_revision(revision_id) -> dict:
    with _db() as conn:
        r = conn.execute("SELECT * FROM artifact_revisions WHERE id=?", (revision_id,)).fetchone()
        return dict(r) if r else None


# ================= 用量 / 审计 / 对话 =================
def insert_usage(trace_id, model, in_tokens, out_tokens, cost, course_id, week_no, file_type,
                 task="", latency_ms=0):
    with _db() as conn:
        conn.execute(
            "INSERT INTO usage(trace_id,model,task,in_tokens,out_tokens,cost,latency_ms,"
            "course_id,week_no,file_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (trace_id, model, task or "", in_tokens, out_tokens, cost, int(latency_ms or 0),
             course_id, week_no, file_type))


def usage_summary(course_id=None) -> dict:
    with _db() as conn:
        where = "WHERE course_id=?" if course_id else ""
        args = (course_id,) if course_id else ()
        total = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(in_tokens),0) tin, "
            f"COALESCE(SUM(out_tokens),0) tout, COALESCE(SUM(cost),0) cost, "
            f"COALESCE(AVG(latency_ms),0) lat FROM usage {where}", args).fetchone()
        by_type = conn.execute(
            f"SELECT file_type, COUNT(*) n, COALESCE(SUM(cost),0) cost "
            f"FROM usage {where} GROUP BY file_type ORDER BY cost DESC", args).fetchall()
        by_model = conn.execute(
            f"SELECT model, COUNT(*) n, COALESCE(SUM(in_tokens+out_tokens),0) tokens, "
            f"COALESCE(SUM(cost),0) cost FROM usage {where} GROUP BY model ORDER BY cost DESC",
            args).fetchall()
        by_day = conn.execute(
            f"SELECT substr(ts,1,10) day, COUNT(*) n, COALESCE(SUM(cost),0) cost "
            f"FROM usage {where} GROUP BY day ORDER BY day DESC LIMIT 7", args).fetchall()
        return {
            "calls": total["n"],
            "in_tokens": total["tin"],
            "out_tokens": total["tout"],
            "cost": round(total["cost"], 4),
            "avg_latency_ms": int(total["lat"] or 0),
            "by_type": _rows(by_type),
            "by_model": _rows(by_model),
            "by_day": list(reversed(_rows(by_day))),
        }


def add_confirm_log(course_id, artifact_id, action, reason=""):
    with _db() as conn:
        conn.execute(
            "INSERT INTO confirm_log(course_id,artifact_id,action,reason) VALUES(?,?,?,?)",
            (course_id, artifact_id, action, (reason or "")[:2000]))


def list_confirm_logs(course_id, limit=30) -> list:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM confirm_log WHERE course_id=? ORDER BY id DESC LIMIT ?",
            (course_id, limit)).fetchall()
        return _rows(rows)


def add_message(course_id, role, text):
    with _db() as conn:
        conn.execute("INSERT INTO conversation(course_id,role,text) VALUES(?,?,?)",
                     (course_id, role, text))
        # 只保留最近 60 条，避免上下文无限增长
        conn.execute(
            "DELETE FROM conversation WHERE course_id=? AND id NOT IN "
            "(SELECT id FROM conversation WHERE course_id=? ORDER BY id DESC LIMIT 60)",
            (course_id, course_id))


def recent_messages(course_id, limit=8) -> list:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation WHERE course_id=? ORDER BY id DESC LIMIT ?",
            (course_id, limit)).fetchall()
        return _rows(reversed(rows))


def clear_messages(course_id):
    with _db() as conn:
        conn.execute("DELETE FROM conversation WHERE course_id=?", (course_id,))


# ================= 后台任务（持久化） =================
def create_task(course_id, kind, payload: dict, total: int) -> str:
    tid = f"t{uuid.uuid4().hex[:10]}"
    with _db() as conn:
        conn.execute(
            "INSERT INTO workflow_tasks(id,course_id,kind,payload,status,done,total,log) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (tid, course_id, kind, json.dumps(payload, ensure_ascii=False),
             "queued", 0, int(total), "[]"))
        _trim_tasks(conn, course_id)
    return tid


def _trim_tasks(conn, course_id):
    conn.execute(
        "DELETE FROM workflow_tasks WHERE course_id=? AND id NOT IN "
        "(SELECT id FROM workflow_tasks WHERE course_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (course_id, course_id, config.MAX_TASK_KEEP))


def _task_row(tid):
    with _db() as conn:
        r = conn.execute("SELECT * FROM workflow_tasks WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None


def get_task(tid) -> dict:
    r = _task_row(tid)
    if not r:
        return None
    try:
        r["payload"] = json.loads(r.get("payload") or "{}")
    except Exception:
        r["payload"] = {}
    try:
        r["log"] = json.loads(r.get("log") or "[]")
    except Exception:
        r["log"] = []
    return r


def update_task(tid, **fields):
    allowed = {"status", "done", "total", "message", "cancel"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            args.append(v)
    if not sets:
        return
    sets.append("updated_at=?")
    args += [_now(), tid]
    with _db() as conn:
        conn.execute(f"UPDATE workflow_tasks SET {','.join(sets)} WHERE id=?", args)


def append_task_log(tid, message):
    with _db() as conn:
        r = conn.execute("SELECT log FROM workflow_tasks WHERE id=?", (tid,)).fetchone()
        if not r:
            return
        try:
            logs = json.loads(r["log"] or "[]")
        except Exception:
            logs = []
        logs.append(f"{(datetime.now()).strftime('%H:%M:%S')}  {message}")
        conn.execute("UPDATE workflow_tasks SET log=?, updated_at=? WHERE id=?",
                     (json.dumps(logs[-200:], ensure_ascii=False), _now(), tid))


def task_cancelled(tid) -> bool:
    r = _task_row(tid)
    return bool(r and r.get("cancel"))


def request_cancel(tid):
    update_task(tid, cancel=1, message="正在取消…")


def list_tasks(course_id, limit=10) -> list:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id,course_id,kind,payload,status,done,total,message,cancel,created_at,updated_at "
            "FROM workflow_tasks WHERE course_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (course_id, limit)).fetchall()
        out = []
        for r in _rows(rows):
            try:
                r["payload"] = json.loads(r.get("payload") or "{}")
            except Exception:
                r["payload"] = {}
            r.pop("cancel", None)
            out.append(r)
        return out


# ================= 公共资源区 =================
VAULT_KINDS = {
    "template": "学校模板",
    "syllabus": "培养方案 / 课程标准",
    "method": "教学方法论",
    "case": "公共案例库",
    "ideo": "思政素材库",
    "other": "其他",
}

_SEED_VAULT = [
    {
        "kind": "template",
        "name": "学校教案模板规范（横版双表）",
        "tags": "教案 模板 横版 双表 栏目 考核",
        "content": (
            "《阳泉师范高等专科学校教案》固定规范：\n"
            "1. A4 横向版式，页眉为「阳泉师范高等专科学校教案」。\n"
            "2. 教案标题下先写「一句话思政核心」，结合本课内容自然融入，不堆口号。\n"
            "3. 表一「教学基本信息」固定 12 个栏目：课题、班级、课时安排、教材、课程类型、"
            "授课地点、教学目标（素养/知识/能力三维，写成可检测条目）、教学重难点（重点/难点）、"
            "学情分析、教学方法、教学资源、教学反思。\n"
            "4. 表二「教学过程环节」固定 5 列：教学环节（名称按本课内容自定义并标注时间）、"
            "教学内容、教师活动、学生活动、设计意图；环节 4–6 个，时间合计必须等于本周学时×45 分钟。\n"
            "5. 教学内容列必须写本周具体知识点、案例、数据、练习；教师活动/学生活动写具体行为与提问；"
            "禁止「讲授本课核心概念」「学生分组讨论」「用直观案例引出主题」「建立系统认知」等空泛套话。\n"
            "6. 每个表格保留 Markdown 分隔行（| --- |），导出时渲染为 Word 表格。"
        ),
    },
    {
        "kind": "method",
        "name": "教学设计方法论（BOPPPS / 目标动词 / 时间分配）",
        "tags": "教学设计 BOPPPS 学情 目标 时间",
        "content": (
            "一、课堂结构建议采用 BOPPPS 变体：导入（Bridge）→ 目标（Objective）→ 前测/提问（Pre-assessment）"
            "→ 参与式学习（Participatory）→ 后测/练习（Post-assessment）→ 小结（Summary）。\n"
            "二、教学目标用可观察、可检测的动词：能说出/能区分/能列出/能按步骤完成/能独立设计/能评价。"
            "避免「了解」「掌握」「理解」单独出现。\n"
            "三、学情分析要写三件事：学生已有的先备知识、可能出现的典型困难、本课采取的应对策略。\n"
            "四、时间分配：2 学时=90 分钟，3 学时=135 分钟，4 学时=180 分钟；导入 5–10 分钟，"
            "讲授不超过总时长 45%，练习/互动不少于 25%，小结与作业 5–8 分钟。\n"
            "五、案例选择优先贴近学生经验（校园、本地产业、岗位场景），每个核心知识点至少配一个正例和一个反例。"
        ),
    },
    {
        "kind": "ideo",
        "name": "课程思政融入指引（一句话思政）",
        "tags": "思政 课程思政 价值观 家国情怀 工匠精神",
        "content": (
            "课程思政应「如盐溶水」，从一个具体知识点或案例自然生长出价值判断，避免贴标签。\n"
            "可用的融入角度：家国情怀与职业理想、工匠精神与精益求精、科技自立自强与创新担当、"
            "质量意识与安全底线、文化自信与中华优秀传统文化、劳动精神与实干笃行、"
            "团队协作与责任担当、绿色发展理念、职业道德与岗位规范。\n"
            "写法：先用一句话点明本课价值主题，再说明它落在哪个教学环节、由哪个案例或数据支撑，"
            "最后给出学生可执行的行为要求（如「在实训记录中如实标注数据来源」）。"
        ),
    },
    {
        "kind": "case",
        "name": "公共案例库使用说明",
        "tags": "案例 校园 本地 行业 情境",
        "content": (
            "案例来源优先级：本校/本地真实事件 > 行业公开报道 > 通用情境案例。\n"
            "每个案例写清：时间地点（可脱敏）、冲突或问题、涉及的知识点、可讨论的问题、"
            "与岗位能力的对应关系。\n"
            "禁止编造具体统计数据、企业名称与人物；无法核实的内容标注「教学情境虚构，仅用于课堂讨论」。\n"
            "案例应在导入或讲授环节出现，并在小结时回收，形成闭环。"
        ),
    },
    {
        "kind": "syllabus",
        "name": "课程标准与培养方案口径",
        "tags": "课程标准 培养方案 岗位 能力 考核",
        "content": (
            "课程目标应对应专业人才培养方案中的毕业要求与岗位能力；教学过程要体现「岗课赛证」融通。\n"
            "考核建议：过程性评价（课堂参与、实训任务、阶段测验）不低于 50%，终结性评价侧重综合任务。\n"
            "每节课的目标要与课程整体目标形成支撑关系，并在教案「教学目标」栏写清可检测条目。"
        ),
    },
]


def _seed_vault():
    with _db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM vault_items").fetchone()[0]
        if n:
            return
        conn.executemany(
            "INSERT INTO vault_items(kind,name,content,tags,enabled) VALUES(?,?,?,?,1)",
            [(i["kind"], i["name"], i["content"], i["tags"]) for i in _SEED_VAULT])


def list_vault(kind=None, include_disabled=True) -> list:
    where, args = [], []
    if kind:
        where.append("kind=?")
        args.append(kind)
    if not include_disabled:
        where.append("enabled=1")
    sql = "SELECT * FROM vault_items" + (" WHERE " + " AND ".join(where) if where else "") \
        + " ORDER BY kind, id"
    with _db() as conn:
        return _rows(conn.execute(sql, args).fetchall())


def get_vault(item_id) -> dict:
    with _db() as conn:
        r = conn.execute("SELECT * FROM vault_items WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None


def create_vault(kind, name, content, tags="") -> int:
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO vault_items(kind,name,content,tags,enabled) VALUES(?,?,?,?,1)",
            (kind or "other", name, content, tags))
        return cur.lastrowid


def update_vault(item_id, **fields):
    allowed = {"kind", "name", "content", "tags", "enabled"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            args.append(v)
    if not sets:
        return
    sets.append("updated_at=?")
    args += [_now(), item_id]
    with _db() as conn:
        conn.execute(f"UPDATE vault_items SET {','.join(sets)} WHERE id=?", args)


def delete_vault(item_id):
    with _db() as conn:
        conn.execute("DELETE FROM vault_items WHERE id=?", (item_id,))


def search_vault(query, limit=3) -> list:
    """公共资源区关键词检索：名称/标签权重更高，返回 enabled 条目。"""
    import re
    items = list_vault(include_disabled=False)
    words = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,6}|[A-Za-z]{3,}", query or "")][:24]
    if not words:
        return items[:limit]
    scored = []
    for it in items:
        name = it.get("name") or ""
        tags = it.get("tags") or ""
        text = it.get("content") or ""
        s = 0.0
        for w in words:
            s += name.count(w) * 6 + tags.count(w) * 4 + min(text.count(w), 3) * 1
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return items[:limit]
    return [it for _, it in scored[:limit]]


def vault_summary() -> list:
    with _db() as conn:
        rows = conn.execute(
            "SELECT kind, COUNT(*) n FROM vault_items WHERE enabled=1 GROUP BY kind").fetchall()
        return _rows(rows)
