from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

LOOKSMAX_EXERCISES = {
    "chintucks": {
        "title": "Чинтакс",
        "unit": "повт.",
        "goal": 15,
        "activity_code": "looks_chintucks",
    },
    "jaw_up": {
        "title": "Наклон головы + челюсть вверх",
        "unit": "сек",
        "goal": 60,
        "activity_code": "looks_jaw_up",
    },
    "jaw_press": {
        "title": "Давить рукой на челюсть",
        "unit": "повт.",
        "goal": 30,
        "activity_code": "looks_jaw_press",
    },
}

FACE_EXERCISES = {
    "forehead": "Лоб",
    "eyes": "Глаза",
    "cheeks": "Щёки",
    "oval": "Овал + шея",
    "massage": "Массаж",
}

def ensure_v3_schema(db):
    with db.conn() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(users)").fetchall()}
        if "face_goal_count" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN face_goal_count INTEGER NOT NULL DEFAULT 0")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS kb_complexes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            local_date TEXT NOT NULL,
            weight REAL NOT NULL,
            rounds INTEGER NOT NULL,
            items_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS face_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            local_date TEXT NOT NULL,
            exercises_json TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        """)

def strength_day(db, user_id, local_date):
    u = db.user(user_id)
    s = db.daily(user_id, local_date)
    pull = float(s["activities"].get("pullup", {}).get("total", 0))
    dips = float(s["activities"].get("dips", {}).get("total", 0))
    return {
        "pull": pull,
        "dips": dips,
        "strength": pull + dips,
        "ok": (
            pull >= float(u["pullup_goal"])
            and dips >= float(u["dips_goal"])
            and pull + dips >= float(u["strength_goal"])
        ),
    }

def current_strength_streak(db, user_id):
    d = db.local_now(user_id).date()
    count = 0
    while strength_day(db, user_id, d.isoformat())["ok"]:
        count += 1
        d -= timedelta(days=1)
    return count

def longest_strength_streak(db, user_id):
    with db.conn() as con:
        rows = con.execute(
            "SELECT DISTINCT local_date FROM logs WHERE user_id=? ORDER BY local_date",
            (user_id,),
        ).fetchall()
    if not rows:
        return 0
    dates = [datetime.fromisoformat(r["local_date"]).date() for r in rows]
    start, end = min(dates), max(dates)
    best = cur = 0
    d = start
    while d <= end:
        if strength_day(db, user_id, d.isoformat())["ok"]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
        d += timedelta(days=1)
    return best

def pr_history(db, user_id, code):
    with db.conn() as con:
        rows = con.execute(
            """SELECT id, amount, local_date, created_at_utc
               FROM logs
               WHERE user_id=? AND activity_code=?
               ORDER BY local_date, created_at_utc, id""",
            (user_id, code),
        ).fetchall()
    result = []
    best = 0.0
    for r in rows:
        amount = float(r["amount"])
        if amount > best:
            result.append({
                "date": r["local_date"],
                "value": amount,
                "delta": (amount - best) if best > 0 else None,
            })
            best = amount
    return result

def strength_recent_days(db, user_id, days=14):
    today = db.local_now(user_id).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        s = db.daily(user_id, d.isoformat())
        out.append({
            "date": d.isoformat(),
            "pull_total": float(s["activities"].get("pullup", {}).get("total", 0)),
            "pull_max": float(s["activities"].get("pullup", {}).get("max_set", 0)),
            "dips_total": float(s["activities"].get("dips", {}).get("total", 0)),
            "dips_max": float(s["activities"].get("dips", {}).get("max_set", 0)),
        })
    return out

def global_stats(db, user_id):
    with db.conn() as con:
        logs = con.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN activity_code='pullup' THEN amount ELSE 0 END),0) pull,
                 COALESCE(SUM(CASE WHEN activity_code='dips' THEN amount ELSE 0 END),0) dips,
                 COALESCE(SUM(CASE WHEN activity_code LIKE 'kb_%' THEN amount ELSE 0 END),0) kb_reps,
                 COUNT(DISTINCT local_date) active_days
               FROM logs WHERE user_id=?""",
            (user_id,),
        ).fetchone()
        runs = con.execute(
            """SELECT COALESCE(SUM(distance_km),0) km, COUNT(*) cnt,
                      COALESCE(SUM(duration_sec),0) sec
               FROM runs WHERE user_id=?""",
            (user_id,),
        ).fetchone()
        water = con.execute(
            "SELECT COALESCE(SUM(ml),0) ml FROM water_logs WHERE user_id=?",
            (user_id,),
        ).fetchone()
        kb_sessions = con.execute(
            "SELECT COUNT(*) c FROM kb_complexes WHERE user_id=?",
            (user_id,),
        ).fetchone()["c"]
        face_sessions = con.execute(
            "SELECT COUNT(*) c FROM face_sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()["c"]

    pull = float(logs["pull"])
    dips = float(logs["dips"])
    return {
        "pull": pull,
        "dips": dips,
        "strength": pull + dips,
        "kb_reps": float(logs["kb_reps"]),
        "active_days": int(logs["active_days"]),
        "run_km": float(runs["km"]),
        "run_count": int(runs["cnt"]),
        "run_sec": int(runs["sec"]),
        "water_l": float(water["ml"]) / 1000,
        "kb_sessions": int(kb_sessions),
        "face_sessions": int(face_sessions),
        "current_streak": current_strength_streak(db, user_id),
        "best_streak": longest_strength_streak(db, user_id),
    }

def add_kb_complex(db, user_id, local_date, weight, rounds, items):
    payload = json.dumps(items, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    with db.conn() as con:
        cur = con.execute(
            """INSERT INTO kb_complexes(user_id, local_date, weight, rounds, items_json, created_at_utc)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, local_date, weight, rounds, payload, now),
        )
        for item in items:
            con.execute(
                """INSERT INTO logs(user_id, activity_code, amount, weight, local_date, created_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    item["code"],
                    float(item["reps"]) * rounds,
                    weight,
                    local_date,
                    now,
                ),
            )
        return int(cur.lastrowid)

def recent_kb_complexes(db, user_id, limit=6):
    with db.conn() as con:
        rows = con.execute(
            """SELECT * FROM kb_complexes WHERE user_id=?
               ORDER BY local_date DESC, id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [
        {
            "date": r["local_date"],
            "weight": float(r["weight"]),
            "rounds": int(r["rounds"]),
            "items": json.loads(r["items_json"]),
        }
        for r in rows
    ]

def add_face_session(db, user_id, local_date, selected):
    selected = [x for x in selected if x in FACE_EXERCISES]
    if not selected:
        return None
    now = datetime.now(timezone.utc).isoformat()
    with db.conn() as con:
        cur = con.execute(
            """INSERT INTO face_sessions(user_id, local_date, exercises_json, created_at_utc)
               VALUES (?, ?, ?, ?)""",
            (user_id, local_date, json.dumps(selected, ensure_ascii=False), now),
        )
        for code in selected:
            con.execute(
                """INSERT INTO logs(user_id, activity_code, amount, weight, local_date, created_at_utc)
                   VALUES (?, ?, 1, NULL, ?, ?)""",
                (user_id, f"face_{code}", local_date, now),
            )
        return int(cur.lastrowid)

def face_progress(db, user_id, local_date):
    with db.conn() as con:
        rows = con.execute(
            """SELECT activity_code, SUM(amount) total
               FROM logs
               WHERE user_id=? AND local_date=? AND activity_code LIKE 'face_%'
               GROUP BY activity_code""",
            (user_id, local_date),
        ).fetchall()
    codes = []
    for r in rows:
        if float(r["total"]) > 0:
            codes.append(r["activity_code"].replace("face_", "", 1))
    codes = list(dict.fromkeys(codes))
    return {
        "count": len(codes),
        "codes": codes,
        "titles": [FACE_EXERCISES.get(x, x) for x in codes],
    }

def is_run_setback(db, run_id):
    run = db.run_by_id(run_id)
    prev = db.previous_run(run["user_id"], exclude_id=run_id)
    if not prev:
        return False
    slower = float(run["pace_sec_km"]) > float(prev["pace_sec_km"]) + 1.0
    shorter = float(run["distance_km"]) < float(prev["distance_km"]) - 0.05
    return slower or shorter


def looksmax_progress(db, user_id, local_date):
    result = {}
    with db.conn() as con:
        rows = con.execute(
            """SELECT activity_code, COALESCE(SUM(amount),0) total
               FROM logs
               WHERE user_id=? AND local_date=? AND activity_code LIKE 'looks_%'
               GROUP BY activity_code""",
            (user_id, local_date),
        ).fetchall()
    totals = {r["activity_code"]: float(r["total"]) for r in rows}
    for code, meta in LOOKSMAX_EXERCISES.items():
        total = totals.get(meta["activity_code"], 0.0)
        result[code] = {
            **meta,
            "total": total,
            "done": total >= float(meta["goal"]),
        }
    return result

def looksmax_all_done(db, user_id, local_date):
    p = looksmax_progress(db, user_id, local_date)
    return all(x["done"] for x in p.values())
