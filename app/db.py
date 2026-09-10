from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

class Database:
    def __init__(self, path: str, default_timezone: str):
        self.path = path
        self.default_timezone = default_timezone
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def conn(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def init(self):
        with self.conn() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
                pullup_goal INTEGER NOT NULL DEFAULT 20,
                dips_goal INTEGER NOT NULL DEFAULT 30,
                strength_goal INTEGER NOT NULL DEFAULT 50,
                water_goal INTEGER NOT NULL DEFAULT 2000,
                run_goal_km REAL NOT NULL DEFAULT 11,
                run_goal_minutes INTEGER NOT NULL DEFAULT 60,
                reminder_times TEXT NOT NULL DEFAULT '11:00,16:00,21:00',
                reminders_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_code TEXT NOT NULL,
                amount REAL NOT NULL,
                weight REAL,
                local_date TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_logs_user_date ON logs(user_id, local_date);

            CREATE TABLE IF NOT EXISTS water_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ml INTEGER NOT NULL,
                local_date TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_water_user_date ON water_logs(user_id, local_date);

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                local_date TEXT NOT NULL,
                place TEXT NOT NULL,
                distance_km REAL NOT NULL,
                duration_sec INTEGER NOT NULL,
                pace_sec_km REAL NOT NULL,
                hardness INTEGER NOT NULL,
                note TEXT,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_runs_user_date ON runs(user_id, local_date);

            CREATE TABLE IF NOT EXISTS custom_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '➕',
                unit TEXT NOT NULL DEFAULT 'повт.',
                kind TEXT NOT NULL DEFAULT 'reps',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY(user_id, code)
            );

            CREATE TABLE IF NOT EXISTS reminder_sent (
                user_id INTEGER NOT NULL,
                local_date TEXT NOT NULL,
                reminder_time TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY(user_id, local_date, reminder_time)
            );
            """)

            cols = {r["name"] for r in con.execute("PRAGMA table_info(users)").fetchall()}
            migrations = {
                "run_goal_km": "ALTER TABLE users ADD COLUMN run_goal_km REAL NOT NULL DEFAULT 11",
                "run_goal_minutes": "ALTER TABLE users ADD COLUMN run_goal_minutes INTEGER NOT NULL DEFAULT 60",
            }
            for col, sql in migrations.items():
                if col not in cols:
                    con.execute(sql)

            # v3.3: custom activities have independent visibility in logging and statistics.
            custom_cols = {r["name"] for r in con.execute("PRAGMA table_info(custom_activities)").fetchall()}
            if "show_in_entry" not in custom_cols:
                con.execute("ALTER TABLE custom_activities ADD COLUMN show_in_entry INTEGER NOT NULL DEFAULT 1")
                con.execute("UPDATE custom_activities SET show_in_entry=active")
            if "show_in_stats" not in custom_cols:
                con.execute("ALTER TABLE custom_activities ADD COLUMN show_in_stats INTEGER NOT NULL DEFAULT 1")

            # One-time cleanup requested by the owner. Remove this test activity and its logs.
            doomed = con.execute(
                "SELECT id FROM custom_activities WHERE lower(trim(title))=lower(?)",
                ("дрочка, ебать",),
            ).fetchall()
            for row in doomed:
                con.execute("DELETE FROM logs WHERE activity_code=?", (f"custom_{row['id']}",))
                con.execute("DELETE FROM custom_activities WHERE id=?", (row["id"],))

    def ensure_user(self, user_id: int, username: str | None, first_name: str | None):
        now = datetime.now(timezone.utc).isoformat()
        with self.conn() as con:
            row = con.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                con.execute(
                    "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
                    (username, first_name, now, user_id),
                )
            else:
                con.execute(
                    """INSERT INTO users (
                       user_id, username, first_name, timezone, pullup_goal, dips_goal,
                       strength_goal, water_goal, run_goal_km, run_goal_minutes,
                       reminder_times, reminders_enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 20, 30, 50, 2000, 11, 60, '11:00,16:00,21:00', 1, ?, ?)""",
                    (user_id, username, first_name, self.default_timezone, now, now),
                )

    def user(self, user_id: int):
        with self.conn() as con:
            row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                raise KeyError(user_id)
            return row

    def local_now(self, user_id: int):
        u = self.user(user_id)
        zone_name = u["timezone"] or self.default_timezone
        try:
            tz = ZoneInfo(zone_name)
        except Exception:
            try:
                tz = ZoneInfo(self.default_timezone)
            except Exception:
                # Windows may not have an IANA timezone database until tzdata is installed.
                # Moscow is UTC+3 year-round, so keep local testing usable as a fallback.
                tz = timezone(timedelta(hours=3))
        return datetime.now(tz)

    def today(self, user_id: int) -> str:
        return self.local_now(user_id).date().isoformat()

    def add_log(self, user_id: int, activity_code: str, amount: float, local_date: str | None = None, weight: float | None = None):
        d = local_date or self.today(user_id)
        with self.conn() as con:
            con.execute(
                """INSERT INTO logs(user_id, activity_code, amount, weight, local_date, created_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, activity_code, amount, weight, d, datetime.now(timezone.utc).isoformat()),
            )

    def add_water(self, user_id: int, ml: int, local_date: str | None = None):
        d = local_date or self.today(user_id)
        with self.conn() as con:
            con.execute(
                """INSERT INTO water_logs(user_id, ml, local_date, created_at_utc)
                   VALUES (?, ?, ?, ?)""",
                (user_id, ml, d, datetime.now(timezone.utc).isoformat()),
            )

    def add_run(self, user_id: int, local_date: str, place: str, distance_km: float, duration_sec: int, hardness: int, note: str | None = None) -> int:
        pace = duration_sec / distance_km
        with self.conn() as con:
            cur = con.execute(
                """INSERT INTO runs(user_id, local_date, place, distance_km, duration_sec,
                   pace_sec_km, hardness, note, created_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, local_date, place, distance_km, duration_sec, pace, hardness, note, datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid)

    def daily(self, user_id: int, local_date: str) -> dict[str, Any]:
        with self.conn() as con:
            rows = con.execute(
                """SELECT activity_code, SUM(amount) AS total, MAX(amount) AS max_set,
                          COUNT(*) AS entries, MAX(weight) AS max_weight
                   FROM logs WHERE user_id=? AND local_date=? GROUP BY activity_code""",
                (user_id, local_date),
            ).fetchall()
            water = con.execute(
                "SELECT COALESCE(SUM(ml),0) AS total FROM water_logs WHERE user_id=? AND local_date=?",
                (user_id, local_date),
            ).fetchone()["total"]
            run = con.execute(
                """SELECT COALESCE(SUM(distance_km),0) AS km, COALESCE(SUM(duration_sec),0) AS sec,
                          COUNT(*) AS count
                   FROM runs WHERE user_id=? AND local_date=?""",
                (user_id, local_date),
            ).fetchone()
        acts = {
            r["activity_code"]: {
                "total": float(r["total"]), "max_set": float(r["max_set"]),
                "entries": int(r["entries"]),
                "max_weight": None if r["max_weight"] is None else float(r["max_weight"]),
            } for r in rows
        }
        return {"activities": acts, "water": int(water), "run_km": float(run["km"]), "run_sec": int(run["sec"]), "run_count": int(run["count"])}

    def update_setting(self, user_id: int, field: str, value: Any):
        allowed = {
            "pullup_goal", "dips_goal", "strength_goal", "water_goal",
            "run_goal_km", "run_goal_minutes", "face_goal_count", "reminder_times",
            "reminders_enabled", "timezone",
        }
        if field not in allowed:
            raise ValueError(field)
        with self.conn() as con:
            con.execute(
                f"UPDATE users SET {field}=?, updated_at=? WHERE user_id=?",
                (value, datetime.now(timezone.utc).isoformat(), user_id),
            )

    def custom_activities(self):
        """Activities visible in the logging menu."""
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM custom_activities WHERE show_in_entry=1 ORDER BY id"
            ).fetchall()

    def custom_activities_for_stats(self):
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM custom_activities WHERE show_in_stats=1 ORDER BY id"
            ).fetchall()

    def all_custom_activities(self):
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM custom_activities ORDER BY id"
            ).fetchall()

    def add_custom_activity(self, title: str, emoji: str, unit: str, kind: str) -> int:
        with self.conn() as con:
            cur = con.execute(
                """INSERT INTO custom_activities(
                       title, emoji, unit, kind, active, show_in_entry, show_in_stats, created_at
                   ) VALUES (?, ?, ?, ?, 1, 1, 1, ?)""",
                (title, emoji or "➕", unit, kind, datetime.now(timezone.utc).isoformat()),
            )
            return int(cur.lastrowid)

    def custom_by_id(self, activity_id: int):
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM custom_activities WHERE id=?",
                (activity_id,),
            ).fetchone()

    def set_custom_visibility(self, activity_id: int, field: str, visible: bool):
        if field not in {"show_in_entry", "show_in_stats"}:
            raise ValueError(field)
        with self.conn() as con:
            con.execute(
                f"UPDATE custom_activities SET {field}=? WHERE id=?",
                (1 if visible else 0, activity_id),
            )

    def custom_totals(self, user_id: int, local_date: str | None = None):
        params = [user_id]
        where_date = ""
        if local_date is not None:
            where_date = " AND l.local_date=?"
            params.append(local_date)
        with self.conn() as con:
            return con.execute(
                f"""SELECT c.id, c.title, c.emoji, c.unit, c.show_in_entry, c.show_in_stats,
                           COALESCE(SUM(l.amount),0) AS total
                    FROM custom_activities c
                    LEFT JOIN logs l
                      ON l.activity_code=('custom_' || c.id) AND l.user_id=?
                    WHERE c.show_in_stats=1{where_date}
                    GROUP BY c.id
                    HAVING COALESCE(SUM(l.amount),0) > 0
                    ORDER BY c.id""",
                params,
            ).fetchall()

    def recent_runs(self, user_id: int, limit: int = 10):
        with self.conn() as con:
            return con.execute(
                """SELECT * FROM runs WHERE user_id=? ORDER BY local_date DESC, id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()

    def previous_run(self, user_id: int, exclude_id: int | None = None):
        with self.conn() as con:
            if exclude_id is None:
                return con.execute(
                    "SELECT * FROM runs WHERE user_id=? ORDER BY local_date DESC, id DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            return con.execute(
                """SELECT * FROM runs WHERE user_id=? AND id<>?
                   ORDER BY local_date DESC, id DESC LIMIT 1""",
                (user_id, exclude_id),
            ).fetchone()

    def run_by_id(self, run_id: int):
        with self.conn() as con:
            return con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    def run_records_before(self, user_id: int, exclude_id: int | None = None):
        with self.conn() as con:
            params = [user_id]
            extra = ""
            if exclude_id is not None:
                extra = " AND id<>?"
                params.append(exclude_id)
            fastest = con.execute(
                f"SELECT MIN(pace_sec_km) AS v FROM runs WHERE user_id=?{extra}",
                params,
            ).fetchone()["v"]
            longest = con.execute(
                f"SELECT MAX(distance_km) AS v FROM runs WHERE user_id=?{extra}",
                params,
            ).fetchone()["v"]
            return {
                "fastest_pace": None if fastest is None else float(fastest),
                "longest_km": None if longest is None else float(longest),
            }

    def run_week_km(self, user_id: int, end_date: str | None = None) -> float:
        end = datetime.fromisoformat(end_date).date() if end_date else self.local_now(user_id).date()
        start = (end - timedelta(days=6)).isoformat()
        with self.conn() as con:
            return float(con.execute(
                """SELECT COALESCE(SUM(distance_km),0) AS km FROM runs
                   WHERE user_id=? AND local_date BETWEEN ? AND ?""",
                (user_id, start, end.isoformat()),
            ).fetchone()["km"])

    def total_runs(self, user_id: int) -> int:
        with self.conn() as con:
            return int(con.execute("SELECT COUNT(*) AS c FROM runs WHERE user_id=?", (user_id,)).fetchone()["c"])

    def records(self, user_id: int):
        with self.conn() as con:
            out = {}
            for code in ("pullup", "dips"):
                out[f"{code}_max_set"] = float(con.execute(
                    "SELECT COALESCE(MAX(amount),0) AS v FROM logs WHERE user_id=? AND activity_code=?",
                    (user_id, code),
                ).fetchone()["v"])
                out[f"{code}_best_day"] = float(con.execute(
                    """SELECT COALESCE(MAX(day_total),0) AS v FROM (
                       SELECT local_date, SUM(amount) AS day_total FROM logs
                       WHERE user_id=? AND activity_code=? GROUP BY local_date
                    )""",
                    (user_id, code),
                ).fetchone()["v"])
            out["water_best_day"] = float(con.execute(
                """SELECT COALESCE(MAX(day_total),0) AS v FROM (
                   SELECT local_date, SUM(ml) AS day_total FROM water_logs
                   WHERE user_id=? GROUP BY local_date
                )""", (user_id,)
            ).fetchone()["v"])
            rr = con.execute(
                """SELECT MAX(distance_km) AS longest, MIN(pace_sec_km) AS fastest
                   FROM runs WHERE user_id=?""", (user_id,)
            ).fetchone()
            out["run_longest"] = 0 if rr["longest"] is None else float(rr["longest"])
            out["run_fastest"] = 0 if rr["fastest"] is None else float(rr["fastest"])
        return out

    def recent_days(self, user_id: int, days: int = 7):
        today = self.local_now(user_id).date()
        return [
            ((today - timedelta(days=i)).isoformat(), self.daily(user_id, (today - timedelta(days=i)).isoformat()))
            for i in range(days)
        ]

    def activity_days_goal_met(self, user_id: int, limit_days: int = 30) -> int:
        u = self.user(user_id)
        days = self.recent_days(user_id, limit_days)
        count = 0
        for _, s in days:
            pull = float(s["activities"].get("pullup", {}).get("total", 0))
            dips = float(s["activities"].get("dips", {}).get("total", 0))
            if pull >= u["pullup_goal"] and dips >= u["dips_goal"] and pull + dips >= u["strength_goal"]:
                count += 1
        return count

    def unlock(self, user_id: int, code: str) -> bool:
        with self.conn() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO achievements(user_id, code, unlocked_at) VALUES (?, ?, ?)",
                (user_id, code, datetime.now(timezone.utc).isoformat()),
            )
            return cur.rowcount > 0

    def achievements(self, user_id: int):
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM achievements WHERE user_id=? ORDER BY unlocked_at DESC",
                (user_id,),
            ).fetchall()

    def users_for_reminders(self):
        with self.conn() as con:
            return con.execute("SELECT * FROM users WHERE reminders_enabled=1").fetchall()

    def reminder_already_sent(self, user_id: int, local_date: str, reminder_time: str) -> bool:
        with self.conn() as con:
            return bool(con.execute(
                """SELECT 1 FROM reminder_sent
                   WHERE user_id=? AND local_date=? AND reminder_time=?""",
                (user_id, local_date, reminder_time),
            ).fetchone())

    def mark_reminder_sent(self, user_id: int, local_date: str, reminder_time: str):
        with self.conn() as con:
            con.execute(
                """INSERT OR IGNORE INTO reminder_sent(user_id, local_date, reminder_time, sent_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, local_date, reminder_time, datetime.now(timezone.utc).isoformat()),
            )

    def users_count(self) -> int:
        with self.conn() as con:
            return int(con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
