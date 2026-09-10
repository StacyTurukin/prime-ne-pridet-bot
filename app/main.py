from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

from .config import load_config
from .data import BUILTIN, KB_CODES, MOTIVATION, REMINDERS, RUN_HARDNESS, ACHIEVEMENTS
from .db import Database
from .features_v3 import (
    ensure_v3_schema, FACE_EXERCISES, current_strength_streak,
    pr_history, strength_recent_days, global_stats, add_kb_complex,
    recent_kb_complexes, add_face_session, face_progress, is_run_setback,
    LOOKSMAX_EXERCISES, looksmax_progress, looksmax_all_done,
)
from .media import (
    send_record_media, send_setback_media,
    send_achievement_media, send_yoga_media,
)
from .ui import (
    main_menu, activity_menu, reps_menu, yoga_menu, kb_exercises, kb_weight, kb_reps,
    water_menu, run_place_menu, run_distance_menu, run_hardness_menu, stats_menu,
    backdate_menu, settings_menu, timezone_menu, admin_menu, unit_menu,
    kb_complex_exercises, kb_complex_controls, kb_complex_rounds, face_menu,
    looksmax_menu, looksmax_amount_menu,
    custom_activity_manage_menu, custom_activity_list_menu,
)

cfg = load_config()
db = Database(cfg.database_path, cfg.default_timezone)
ensure_v3_schema(db)
router = Router()

class Flow(StatesGroup):
    custom_reps = State()
    custom_yoga = State()
    custom_water = State()
    kb_weight = State()
    kb_reps = State()
    custom_activity_amount = State()
    setting_value = State()
    reminder_times = State()
    admin_title = State()
    admin_unit = State()
    custom_date = State()
    custom_run_place = State()
    run_distance = State()
    run_duration = State()
    run_note = State()
    kb_complex_reps = State()
    kb_complex_rounds = State()
    looksmax_custom = State()

def fmt_num(v):
    v = float(v)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.2f}".rstrip("0").rstrip(".")

def fmt_duration(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fmt_pace(sec_per_km):
    if not sec_per_km:
        return "—"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/км"

def parse_duration(text):
    t = text.strip().replace(".", ":")
    parts = t.split(":")
    try:
        nums = [int(x) for x in parts]
    except Exception:
        raise ValueError("bad time")
    if len(nums) == 2:
        m, s = nums
        if not (0 <= s < 60):
            raise ValueError("bad time")
        return m * 60 + s
    if len(nums) == 3:
        h, m, s = nums
        if not (0 <= m < 60 and 0 <= s < 60):
            raise ValueError("bad time")
        return h * 3600 + m * 60 + s
    raise ValueError("bad time")

def bar(done, goal, width=10):
    if float(goal) <= 0:
        return "──────────"
    ratio = max(0, min(1, float(done) / float(goal)))
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled)

def get_log_date(user_id, state_data):
    return state_data.get("log_date") or db.today(user_id)

def activity_total(summary, code):
    return float(summary["activities"].get(code, {}).get("total", 0))

def activity_max(summary, code):
    return float(summary["activities"].get(code, {}).get("max_set", 0))

def delta_text(today, yesterday, unit=""):
    diff = float(today) - float(yesterday)
    if abs(diff) < 1e-9:
        return "как вчера"
    return f"{'▲ +' if diff > 0 else '▼ −'}{fmt_num(abs(diff))}{(' ' + unit) if unit else ''} к вчера"

async def ensure(message):
    u = message.from_user
    db.ensure_user(u.id, u.username, u.first_name)

def achievement_meta(code):
    if code.startswith("streak_"):
        n = int(code.split("_", 1)[1])
        return (
            f"🔥 {n} ДНЕЙ БЕЗ ПРОПУСКА",
            f"Обязательный минимум закрыт {n} дней подряд. Это уже не случайность, брат.",
        )
    return ACHIEVEMENTS.get(
        code,
        ("🎖 Ачивка", "Ещё одна цифра решила стать приятной."),
    )

async def maybe_unlock_basic(user_id, local_date):
    unlocked = []
    s = db.daily(user_id, local_date)
    total_entries = sum(a["entries"] for a in s["activities"].values())

    if total_entries and db.unlock(user_id, "first_log"):
        unlocked.append("first_log")
    if activity_total(s, "pullup") >= 50 and db.unlock(user_id, "pullup_50_day"):
        unlocked.append("pullup_50_day")
    if activity_total(s, "dips") >= 75 and db.unlock(user_id, "dips_75_day"):
        unlocked.append("dips_75_day")
    if s["water"] >= db.user(user_id)["water_goal"] and db.unlock(user_id, "water_goal"):
        unlocked.append("water_goal")
    if activity_total(s, "yoga") >= 30 and db.unlock(user_id, "yoga_30"):
        unlocked.append("yoga_30")

    if local_date == db.today(user_id):
        streak = current_strength_streak(db, user_id)
        if streak >= 2:
            code = f"streak_{streak}"
            if db.unlock(user_id, code):
                unlocked.append(code)

    return unlocked

async def achievement_text(codes):
    if not codes:
        return ""
    blocks = []
    for code in codes:
        title, desc = achievement_meta(code)
        blocks.append(f"🎖 <b>АЧИВКА: {escape(title)}</b>\n{escape(desc)}")
    return "\n\n" + "\n\n".join(blocks)

async def send_codes_media(bot, chat_id, codes):
    if not codes:
        return
    major = any(
        code.startswith("streak_") and int(code.split("_")[1]) >= 5
        for code in codes
    )
    major = major or any(
        code in {"run_11k_sub60", "run_week_50", "run_pace_pb", "run_distance_pb"}
        for code in codes
    )
    if "yoga_30" in codes:
        await send_yoga_media(bot, chat_id)
    else:
        await send_achievement_media(bot, chat_id, major=major)

def daily_report(user_id, local_date=None):
    u = db.user(user_id)
    d = local_date or db.today(user_id)
    s = db.daily(user_id, d)
    d_obj = datetime.fromisoformat(d).date()
    y = db.daily(user_id, (d_obj - timedelta(days=1)).isoformat())

    pull, dips = activity_total(s, "pullup"), activity_total(s, "dips")
    pull_y, dips_y = activity_total(y, "pullup"), activity_total(y, "dips")
    strength = pull + dips

    lines = [
        f"<b>📊 {d_obj.strftime('%d.%m.%Y')}</b>",
        "",
        f"🧗 <b>Турник:</b> {fmt_num(pull)} / {u['pullup_goal']} · лучший подход {fmt_num(activity_max(s, 'pullup'))}",
        f"{bar(pull, u['pullup_goal'])}  {delta_text(pull, pull_y, 'повт.')}",
        "",
        f"💪 <b>Брусья:</b> {fmt_num(dips)} / {u['dips_goal']} · лучший подход {fmt_num(activity_max(s, 'dips'))}",
        f"{bar(dips, u['dips_goal'])}  {delta_text(dips, dips_y, 'повт.')}",
        "",
        f"🔥 <b>Силовой минимум:</b> {fmt_num(strength)} / {u['strength_goal']}",
        bar(strength, u["strength_goal"]),
        "",
        f"🏃 <b>Бег:</b> {fmt_num(s['run_km'])} км · {fmt_duration(s['run_sec']) if s['run_sec'] else '—'}",
        f"💧 <b>Вода:</b> {s['water']} / {u['water_goal']} мл",
        bar(s["water"], u["water_goal"]),
    ]

    looks = looksmax_progress(db, user_id, d)
    if any(item["total"] > 0 for item in looks.values()):
        lines += ["", "🗿 <b>Луксмаксинг, ебать:</b>"]
        for item in looks.values():
            lines.append(
                f"• {item['title']}: <b>{fmt_num(item['total'])}/{item['goal']} {item['unit']}</b> "
                f"{'✅' if item['done'] else '⏳'}"
            )

    yoga = activity_total(s, "yoga")
    if yoga:
        lines += ["", f"🧘 Йога: <b>{fmt_num(yoga)} мин</b>"]

    kb = []
    for code in KB_CODES:
        if code in s["activities"]:
            a = s["activities"][code]
            w = f" · до {fmt_num(a['max_weight'])} кг" if a["max_weight"] else ""
            kb.append(f"• {BUILTIN[code]['title']}: {fmt_num(a['total'])} повт.{w}")
    if kb:
        lines += ["", "🟠 <b>Гиря:</b>"] + kb

    custom_rows = db.custom_totals(user_id, d)
    if custom_rows:
        lines += ["", "➕ <b>Свои активности:</b>"]
        for row in custom_rows:
            lines.append(
                f"• {escape(row['emoji'])} {escape(row['title'])}: "
                f"<b>{fmt_num(row['total'])} {escape(row['unit'])}</b>"
            )

    complete = pull >= u["pullup_goal"] and dips >= u["dips_goal"] and strength >= u["strength_goal"]
    if complete:
        lines += ["", "✅ <b>Обязательный минимум закрыт.</b>", random.choice(MOTIVATION)]
    else:
        rem = []
        if pull < u["pullup_goal"]:
            rem.append(f"турник {int(u['pullup_goal']-pull)}")
        if dips < u["dips_goal"]:
            rem.append(f"брусья {int(u['dips_goal']-dips)}")
        if strength < u["strength_goal"]:
            rem.append(f"общий {int(u['strength_goal']-strength)}")
        lines += ["", f"⏳ Осталось: <b>{escape(', '.join(rem))}</b>.", random.choice(MOTIVATION)]
    return "\n".join(lines)

def run_compare_text(run_id):
    run = db.run_by_id(run_id)
    prev = db.previous_run(run["user_id"], exclude_id=run_id)
    lines = []
    if prev:
        pace_diff = float(prev["pace_sec_km"]) - float(run["pace_sec_km"])
        dist_diff = float(run["distance_km"]) - float(prev["distance_km"])
        if abs(pace_diff) < 0.5:
            pace_line = "Темп почти идентичный прошлой пробежке."
        elif pace_diff > 0:
            pace_line = f"⚡ Темп быстрее прошлой на <b>{int(round(pace_diff))} сек/км</b>."
        else:
            pace_line = f"🐢 Темп медленнее прошлой на <b>{int(round(abs(pace_diff)))} сек/км</b>."
        lines += [
            "",
            "<b>Против прошлой пробежки:</b>",
            pace_line,
            f"📏 Дистанция: {'+' if dist_diff >= 0 else '−'}{fmt_num(abs(dist_diff))} км",
            f"Прошлая: {fmt_num(prev['distance_km'])} км · {fmt_pace(prev['pace_sec_km'])}",
        ]
    return "\n".join(lines)

def run_goal_text(user_id, run):
    u = db.user(user_id)
    goal_km = float(u["run_goal_km"])
    goal_sec = int(u["run_goal_minutes"]) * 60
    target_pace = goal_sec / goal_km if goal_km > 0 else 0

    lines = [
        "",
        f"🎯 Цель: <b>{fmt_num(goal_km)} км из {u['run_goal_minutes']} мин</b>",
        f"Нужный средний темп: <b>{fmt_pace(target_pace)}</b>",
    ]
    if float(run["distance_km"]) >= goal_km:
        delta = int(run["duration_sec"]) - goal_sec
        if delta <= 0:
            lines.append(f"🚀 Цель закрыта с запасом <b>{fmt_duration(abs(delta))}</b>.")
        else:
            lines.append(f"До цели по времени: <b>{fmt_duration(delta)}</b>.")
    else:
        lines.append(f"До целевой дистанции: <b>{fmt_num(goal_km-float(run['distance_km']))} км</b>.")
    return "\n".join(lines)

async def unlock_run_achievements(user_id, run_id):
    run = db.run_by_id(run_id)
    old = db.run_records_before(user_id, exclude_id=run_id)
    codes = []
    km, sec, pace = float(run["distance_km"]), int(run["duration_sec"]), float(run["pace_sec_km"])

    def hit(code, condition=True):
        if condition and db.unlock(user_id, code):
            codes.append(code)

    hit("run_first", db.total_runs(user_id) >= 1)
    hit("run_5k", km >= 5)
    hit("run_10k", km >= 10)
    hit("run_10k_sub60", km >= 10 and pace <= 360)
    hit("run_11k", km >= 11)
    hit("run_11k_sub60", km >= 11 and sec <= 3600)
    hit("run_pace_pb", old["fastest_pace"] is not None and pace < old["fastest_pace"] - 0.5)
    hit("run_distance_pb", old["longest_km"] is not None and km > old["longest_km"] + 1e-9)

    week = db.run_week_km(user_id, run["local_date"])
    hit("run_week_30", week >= 30)
    hit("run_week_50", week >= 50)
    return codes

def run_summary(run_id):
    r = db.run_by_id(run_id)
    speed = float(r["distance_km"]) / (float(r["duration_sec"]) / 3600)
    return (
        f"<b>🏃 ПРОБЕЖКА ЗАПИСАНА</b>\n\n"
        f"📍 {escape(r['place'])}\n"
        f"📏 <b>{fmt_num(r['distance_km'])} км</b>\n"
        f"⏱ <b>{fmt_duration(r['duration_sec'])}</b>\n"
        f"⚡ <b>{fmt_pace(r['pace_sec_km'])}</b>\n"
        f"🚀 {speed:.2f} км/ч\n"
        f"🫀 Сложность: <b>{escape(RUN_HARDNESS[int(r['hardness'])])}</b>"
        + run_compare_text(run_id)
        + run_goal_text(r["user_id"], r)
    )

def runs_report(user_id):
    rows = db.recent_runs(user_id, 8)
    if not rows:
        return "🏃 Пробежек пока нет. Даже Nike Run Club когда-то был пустым."
    rec = db.records(user_id)
    lines = [
        "<b>🏃 БЕГОВОЙ ЖУРНАЛ</b>",
        "",
        f"⚡ Лучший темп: <b>{fmt_pace(rec['run_fastest'])}</b>",
        f"📏 Самая длинная: <b>{fmt_num(rec['run_longest'])} км</b>",
        f"📆 За 7 дней: <b>{fmt_num(db.run_week_km(user_id))} км</b>",
        "",
    ]
    for r in rows:
        lines.append(
            f"• {r['local_date'][5:]} · {escape(r['place'])} · "
            f"<b>{fmt_num(r['distance_km'])} км</b> · {fmt_duration(r['duration_sec'])} · "
            f"{fmt_pace(r['pace_sec_km'])} · {int(r['hardness'])}/5"
        )
    return "\n".join(lines)

def records_report(user_id):
    r = db.records(user_id)
    return (
        "<b>🏆 РЕКОРДЫ</b>\n\n"
        f"🧗 Лучший подход на турнике: <b>{fmt_num(r['pullup_max_set'])}</b>\n"
        f"🧗 Лучший день на турнике: <b>{fmt_num(r['pullup_best_day'])}</b>\n\n"
        f"💪 Лучший подход на брусьях: <b>{fmt_num(r['dips_max_set'])}</b>\n"
        f"💪 Лучший день на брусьях: <b>{fmt_num(r['dips_best_day'])}</b>\n\n"
        f"🏃 Самая длинная пробежка: <b>{fmt_num(r['run_longest'])} км</b>\n"
        f"⚡ Лучший средний темп: <b>{fmt_pace(r['run_fastest'])}</b>\n"
        f"💧 Максимум воды за день: <b>{int(r['water_best_day'])} мл</b>"
    )

def week_report(user_id):
    u = db.user(user_id)
    days = list(reversed(db.recent_days(user_id, 7)))
    lines = ["<b>🗓 7 ДНЕЙ</b>", ""]
    completed = 0
    for d, s in days:
        p, dip = activity_total(s, "pullup"), activity_total(s, "dips")
        ok = p >= u["pullup_goal"] and dip >= u["dips_goal"] and p + dip >= u["strength_goal"]
        completed += int(ok)
        lines.append(f"{'✅' if ok else '·'} {d[5:]}  🧗 {fmt_num(p)}  💪 {fmt_num(dip)}  🏃 {fmt_num(s['run_km'])}  💧 {s['water']}")
    lines += ["", f"🔥 Дней с закрытым минимумом: <b>{completed}/7</b>", f"🏃 Бега за 7 дней: <b>{fmt_num(db.run_week_km(user_id))} км</b>"]
    return "\n".join(lines)

def settings_text(user_id):
    u = db.user(user_id)
    return (
        "<b>⚙️ НАСТРОЙКИ</b>\n\n"
        f"🧗 Турник: <b>{u['pullup_goal']}</b>\n"
        f"💪 Брусья: <b>{u['dips_goal']}</b>\n"
        f"🔥 Общий минимум: <b>{u['strength_goal']}</b>\n"
        f"💧 Вода: <b>{u['water_goal']} мл</b>\n"
        f"🏃 Беговая цель: <b>{fmt_num(u['run_goal_km'])} км из {u['run_goal_minutes']} мин</b>\n"
        f"⏰ Напоминания: <b>{'вкл' if u['reminders_enabled'] else 'выкл'}</b>\n"
        f"🕒 {escape(u['reminder_times'])}\n"
        f"🌍 {escape(u['timezone'])}"
    )

def achievements_report(user_id):
    rows = db.achievements(user_id)
    unlocked = {r["code"] for r in rows}
    lines = ["<b>🎖 АЧИВКИ</b>", ""]

    for code, (title, desc) in ACHIEVEMENTS.items():
        lines.append(f"{'✅' if code in unlocked else '🔒'} <b>{escape(title)}</b>")
        if code in unlocked:
            lines.append(escape(desc))

    streaks = sorted(
        [
            int(r["code"].split("_", 1)[1])
            for r in rows
            if r["code"].startswith("streak_")
        ],
        reverse=True,
    )
    if streaks:
        lines += [
            "",
            f"🔥 Лучшая серия-ачивка: <b>{max(streaks)} дней</b>",
            "Каждый следующий закрытый день выдаст новую цифру. Никаких «ждите 30 дней ради медальки».",
        ]

    return "\n".join(lines)

async def open_activity_menu(message_or_callback, state):
    data = await state.get_data()
    d = data.get("log_date")
    prefix = f"🗓 Записываем за <b>{d}</b>.\n\n" if d else ""
    await message_or_callback.answer(prefix + "Что сделал?", reply_markup=activity_menu(db.custom_activities()))

@router.message(CommandStart())
async def start(message):
    await ensure(message)
    await message.answer(
        "<b>🔥 ПРАЙМ НЕ ПРИДЁТ, ЕСЛИ ПРОСТО ЖДАТЬ</b>\n\n"
        "Не надо рвать жопу каждый день и превращать жизнь в рекламу энергетика.\n"
        "Надо видеть факты: подходы, километры, воду, рекорды и закрытый минимум.\n\n"
        "Турник, брусья, гиря, бег, йога, вода и луксмаксинг — в пару тыков. "
        "Когда мозг говорит «ты опять ничего не сделал», открываешь цифры и проверяешь, пиздит он или нет.",
        reply_markup=main_menu(),
    )

@router.message(Command("myid"))
async def myid(message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")

@router.message(F.text == "🏋️ Записать")
async def log_menu(message, state):
    await ensure(message)
    await open_activity_menu(message, state)

@router.message(Command("run"))
async def run_direct(message, state):
    await ensure(message)
    await state.update_data(run_mode=True)
    await message.answer("🏃 Где бегал?", reply_markup=run_place_menu())

@router.callback_query(F.data == "act:run")
async def run_from_menu(c, state):
    await c.answer()
    await state.update_data(run_mode=True)
    await c.message.answer("🏃 Где бегал?", reply_markup=run_place_menu())

@router.callback_query(F.data.startswith("runplace:"))
async def run_place(c, state):
    await c.answer()
    place = c.data.split(":", 1)[1]
    if place == "Другое":
        await state.set_state(Flow.custom_run_place)
        await c.message.answer("Напиши место. Например: <b>набережная</b>")
        return
    await state.update_data(run_place=place)
    await c.message.edit_text(f"📍 {escape(place)}.\nСколько километров?", reply_markup=run_distance_menu())

@router.message(Flow.custom_run_place)
async def run_place_custom(message, state):
    place = message.text.strip()[:60]
    await state.update_data(run_place=place)
    await state.set_state(None)
    await message.answer(f"📍 {escape(place)}.\nСколько километров?", reply_markup=run_distance_menu())

@router.callback_query(F.data.startswith("rundist:"))
async def run_distance(c, state):
    await c.answer()
    val = c.data.split(":", 1)[1]
    if val == "custom":
        await state.set_state(Flow.run_distance)
        await c.message.answer("Напиши дистанцию в км. Например: <b>11</b> или <b>7.35</b>")
        return
    await state.update_data(run_distance=float(val))
    await state.set_state(Flow.run_duration)
    await c.message.answer("⏱ Общее время?\nФормат <code>58:42</code> или <code>1:03:20</code>")

@router.message(Flow.run_distance)
async def run_distance_custom(message, state):
    try:
        km = float(message.text.replace(",", "."))
        if not (0.1 <= km <= 200):
            raise ValueError
    except Exception:
        await message.answer("Нужны километры числом. Например: <b>11</b>")
        return
    await state.update_data(run_distance=km)
    await state.set_state(Flow.run_duration)
    await message.answer("⏱ Общее время?\nФормат <code>58:42</code> или <code>1:03:20</code>")

@router.message(Flow.run_duration)
async def run_duration(message, state):
    try:
        sec = parse_duration(message.text)
        if sec < 60 or sec > 24 * 3600:
            raise ValueError
    except Exception:
        await message.answer("Не понял время. Пример: <code>58:42</code> или <code>1:03:20</code>")
        return
    data = await state.get_data()
    pace = sec / float(data["run_distance"])
    await state.update_data(run_duration=sec)
    await state.set_state(None)
    await message.answer(
        f"⚡ Средний темп получается <b>{fmt_pace(pace)}</b>.\n"
        "А теперь главный научный показатель: насколько это была жопа?",
        reply_markup=run_hardness_menu(),
    )

@router.callback_query(F.data.startswith("runhard:"))
async def run_hard(c, state):
    await c.answer()
    hardness = int(c.data.split(":")[1])
    data = await state.get_data()
    local_date = get_log_date(c.from_user.id, data)
    run_id = db.add_run(
        c.from_user.id, local_date, data["run_place"],
        float(data["run_distance"]), int(data["run_duration"]), hardness,
    )
    run_codes = await unlock_run_achievements(c.from_user.id, run_id)
    setback = is_run_setback(db, run_id)
    await state.clear()
    await c.message.edit_text(run_summary(run_id) + await achievement_text(run_codes))

    if setback:
        await send_setback_media(c.bot, c.message.chat.id)
    if run_codes:
        await send_codes_media(c.bot, c.message.chat.id, run_codes)

@router.callback_query(F.data == "act:pullup")
async def pullup(c):
    await c.answer()
    await c.message.edit_text("🧗 Сколько было в <b>этом подходе</b>?", reply_markup=reps_menu("pullup"))

@router.callback_query(F.data == "act:dips")
async def dips(c):
    await c.answer()
    await c.message.edit_text("💪 Сколько было в <b>этом подходе</b>?", reply_markup=reps_menu("dips"))

@router.callback_query(F.data.startswith("reps:"))
async def reps(c, state):
    await c.answer()
    _, code, val = c.data.split(":")
    amount = int(val)
    data = await state.get_data()
    d = get_log_date(c.from_user.id, data)

    old_best = (
        db.records(c.from_user.id).get(f"{code}_max_set", 0)
        if code in {"pullup", "dips"}
        else 0
    )

    db.add_log(c.from_user.id, code, amount, d)
    s = db.daily(c.from_user.id, d)
    codes = await maybe_unlock_basic(c.from_user.id, d)

    new_pr = code in {"pullup", "dips"} and amount > float(old_best)
    if new_pr:
        if old_best > 0:
            pr_line = f"\n\n🚨 <b>НОВЫЙ PR: {fmt_num(old_best)} → {amount}</b> · {d}"
        else:
            pr_line = f"\n\n📌 Базовый PR установлен: <b>{amount}</b> · {d}"
    else:
        pr_line = ""

    await state.clear()
    await c.message.edit_text(
        f"✅ <b>{BUILTIN[code]['title']}: +{amount}</b>\n"
        f"За {d}: <b>{fmt_num(activity_total(s, code))}</b>\n"
        f"Лучший подход: <b>{fmt_num(activity_max(s, code))}</b>"
        f"{pr_line}\n\n{random.choice(MOTIVATION)}"
        + await achievement_text(codes)
    )

    if new_pr and old_best > 0:
        await send_record_media(c.bot, c.message.chat.id)
    await send_codes_media(c.bot, c.message.chat.id, codes)

@router.callback_query(F.data.startswith("repscustom:"))
async def reps_custom(c, state):
    await c.answer()
    await state.update_data(activity_code=c.data.split(":",1)[1])
    await state.set_state(Flow.custom_reps)
    await c.message.answer("Напиши число повторений.")

@router.message(Flow.custom_reps)
async def reps_custom_val(message, state):
    try:
        amount = int(message.text)
        if amount <= 0 or amount > 5000:
            raise ValueError
    except Exception:
        await message.answer("Нужно положительное целое число.")
        return

    data = await state.get_data()
    d = get_log_date(message.from_user.id, data)
    code = data["activity_code"]

    old_best = (
        db.records(message.from_user.id).get(f"{code}_max_set", 0)
        if code in {"pullup", "dips"}
        else 0
    )

    db.add_log(message.from_user.id, code, amount, d)
    codes = await maybe_unlock_basic(message.from_user.id, d)
    new_pr = code in {"pullup", "dips"} and amount > float(old_best)

    if new_pr:
        extra = (
            f"\n\n🚨 <b>НОВЫЙ PR: {fmt_num(old_best)} → {amount}</b> · {d}"
            if old_best > 0
            else f"\n\n📌 Базовый PR установлен: <b>{amount}</b> · {d}"
        )
    else:
        extra = ""

    await state.clear()
    await message.answer(
        f"✅ +{amount}. {random.choice(MOTIVATION)}{extra}"
        + await achievement_text(codes),
        reply_markup=main_menu(),
    )

    if new_pr and old_best > 0:
        await send_record_media(message.bot, message.chat.id)
    await send_codes_media(message.bot, message.chat.id, codes)

@router.callback_query(F.data == "act:yoga")
async def yoga(c):
    await c.answer()
    await c.message.edit_text("🧘 Сколько минут?", reply_markup=yoga_menu())

@router.callback_query(F.data.startswith("yoga:"))
async def yoga_val(c, state):
    await c.answer()
    mins = int(c.data.split(":")[1])
    data = await state.get_data()
    d = get_log_date(c.from_user.id, data)
    db.add_log(c.from_user.id, "yoga", mins, d)
    codes = await maybe_unlock_basic(c.from_user.id, d)
    await state.clear()
    await c.message.edit_text(
        f"✅ Йога: <b>+{mins} мин</b>. Позвоночник пока не подал заявление на увольнение."
        + await achievement_text(codes)
    )
    await send_codes_media(c.bot, c.message.chat.id, codes)

@router.callback_query(F.data == "yogacustom")
async def yoga_custom(c, state):
    await c.answer()
    await state.set_state(Flow.custom_yoga)
    await c.message.answer("Напиши минуты.")

@router.message(Flow.custom_yoga)
async def yoga_custom_val(message, state):
    try:
        mins = int(message.text)
        if mins <= 0 or mins > 600: raise ValueError
    except Exception:
        await message.answer("Нужно целое число минут.")
        return
    data = await state.get_data()
    d = get_log_date(message.from_user.id, data)
    db.add_log(message.from_user.id, "yoga", mins, d)
    codes = await maybe_unlock_basic(message.from_user.id, d)
    await state.clear()
    await message.answer(
        f"✅ Йога: +{mins} мин." + await achievement_text(codes),
        reply_markup=main_menu(),
    )
    await send_codes_media(message.bot, message.chat.id, codes)

@router.callback_query(F.data == "act:kb")
async def kb(c):
    await c.answer()
    await c.message.edit_text("🟠 Что делал с гирей?", reply_markup=kb_exercises())

@router.callback_query(F.data.startswith("kbex:"))
async def kb_ex(c, state):
    await c.answer()
    code = c.data.split(":",1)[1]
    await state.update_data(kb_code=code)
    await c.message.edit_text(f"{BUILTIN[code]['title']}\n\nКакой вес?", reply_markup=kb_weight())

@router.callback_query(F.data.startswith("kbw:"))
async def kb_w(c, state):
    await c.answer()
    w = float(c.data.split(":")[1])
    await state.update_data(kb_weight=w)
    data = await state.get_data()

    if data.get("kb_complex"):
        await c.message.edit_text(
            f"Гиря <b>{fmt_num(w)} кг</b>. Добавь упражнения в один круг:",
            reply_markup=kb_complex_exercises(),
        )
    else:
        await c.message.edit_text(
            f"Гиря <b>{fmt_num(w)} кг</b>. Сколько повторений?",
            reply_markup=kb_reps(),
        )

@router.callback_query(F.data == "kbwcustom")
async def kb_w_custom(c, state):
    await c.answer()
    await state.set_state(Flow.kb_weight)
    await c.message.answer("Напиши вес гири в кг.")

@router.message(Flow.kb_weight)
async def kb_w_custom_val(message, state):
    try:
        w = float(message.text.replace(",", "."))
        if w <= 0 or w > 200: raise ValueError
    except Exception:
        await message.answer("Вес числом, брат.")
        return
    await state.update_data(kb_weight=w)
    await state.set_state(None)
    data = await state.get_data()

    if data.get("kb_complex"):
        await message.answer(
            f"Гиря <b>{fmt_num(w)} кг</b>. Добавь упражнения в один круг:",
            reply_markup=kb_complex_exercises(),
        )
    else:
        await message.answer(
            f"Гиря <b>{fmt_num(w)} кг</b>. Сколько повторений?",
            reply_markup=kb_reps(),
        )

@router.callback_query(F.data.startswith("kbr:"))
async def kb_r(c, state):
    await c.answer()
    reps = int(c.data.split(":")[1])
    data = await state.get_data()
    d = get_log_date(c.from_user.id, data)
    db.add_log(c.from_user.id, data["kb_code"], reps, d, float(data["kb_weight"]))
    await state.clear()
    await c.message.edit_text(f"✅ {BUILTIN[data['kb_code']]['title']}: <b>{fmt_num(data['kb_weight'])} кг × {reps}</b>\n\n{random.choice(MOTIVATION)}")

@router.callback_query(F.data == "kbrcustom")
async def kb_r_custom(c, state):
    await c.answer()
    await state.set_state(Flow.kb_reps)
    await c.message.answer("Напиши количество повторений.")

@router.message(Flow.kb_reps)
async def kb_r_custom_val(message, state):
    try:
        reps = int(message.text)
        if reps <= 0 or reps > 5000: raise ValueError
    except Exception:
        await message.answer("Нужно целое число.")
        return
    data = await state.get_data()
    d = get_log_date(message.from_user.id, data)
    db.add_log(message.from_user.id, data["kb_code"], reps, d, float(data["kb_weight"]))
    await state.clear()
    await message.answer(f"✅ {BUILTIN[data['kb_code']]['title']}: {fmt_num(data['kb_weight'])} кг × {reps}.", reply_markup=main_menu())

@router.message(F.text == "💧 Вода")
async def water(message):
    await ensure(message)
    await message.answer("💧 Сколько залить в человека?", reply_markup=water_menu())

@router.callback_query(F.data.startswith("water:"))
async def water_val(c, state):
    await c.answer()
    ml = int(c.data.split(":")[1])
    data = await state.get_data()
    d = get_log_date(c.from_user.id, data)
    db.add_water(c.from_user.id, ml, d)
    total = db.daily(c.from_user.id, d)["water"]
    goal = db.user(c.from_user.id)["water_goal"]
    codes = await maybe_unlock_basic(c.from_user.id, d)
    await state.clear()
    await c.message.edit_text(f"💧 <b>+{ml} мл</b>\nЗа {d}: <b>{total}/{goal} мл</b>\n{bar(total, goal)}" + await achievement_text(codes))

@router.callback_query(F.data == "watercustom")
async def water_custom(c, state):
    await c.answer()
    await state.set_state(Flow.custom_water)
    await c.message.answer("Напиши миллилитры.")

@router.message(Flow.custom_water)
async def water_custom_val(message, state):
    try:
        ml = int(message.text)
        if ml <= 0 or ml > 5000: raise ValueError
    except Exception:
        await message.answer("Нужно целое число мл.")
        return
    data = await state.get_data()
    d = get_log_date(message.from_user.id, data)
    db.add_water(message.from_user.id, ml, d)
    codes = await maybe_unlock_basic(message.from_user.id, d)
    await state.clear()
    await message.answer(f"💧 +{ml} мл." + await achievement_text(codes), reply_markup=main_menu())

@router.message(F.text == "🗓 Задним числом")
async def backdate(message):
    await ensure(message)
    await message.answer("За какой день дописываем историю побед?", reply_markup=backdate_menu())

@router.callback_query(F.data.startswith("backdate:"))
async def backdate_pick(c, state):
    await c.answer()
    val = c.data.split(":",1)[1]
    if val == "custom":
        await state.set_state(Flow.custom_date)
        await c.message.answer("Дата в формате <code>2026-09-08</code>")
        return
    d = (db.local_now(c.from_user.id).date() - timedelta(days=int(val))).isoformat()
    await state.update_data(log_date=d)
    await c.message.answer(f"🗓 Ок, пишем за <b>{d}</b>.\nЧто добавить?", reply_markup=activity_menu(db.custom_activities()))
    await c.message.answer("Если это вода — жми кнопку «💧 Вода» внизу. Дата сохранится до первой записи.")

@router.message(Flow.custom_date)
async def custom_date(message, state):
    try:
        d = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
        if d > db.local_now(message.from_user.id).date():
            raise ValueError
    except Exception:
        await message.answer("Нужна прошедшая дата: <code>2026-09-08</code>")
        return
    await state.update_data(log_date=d.isoformat())
    await state.set_state(None)
    await message.answer(f"🗓 Пишем за <b>{d.isoformat()}</b>.", reply_markup=activity_menu(db.custom_activities()))

@router.message(Command("today"))
@router.message(F.text == "📊 Сегодня")
async def today(message):
    await ensure(message)
    await message.answer(daily_report(message.from_user.id), reply_markup=main_menu())

@router.message(Command("stats"))
@router.message(F.text == "📈 Статистика")
async def stats(message):
    await ensure(message)
    await message.answer("Что смотрим?", reply_markup=stats_menu())

@router.callback_query(F.data == "stats:today")
async def stats_today(c):
    await c.answer()
    await c.message.answer(daily_report(c.from_user.id))

@router.callback_query(F.data == "stats:week")
async def stats_week(c):
    await c.answer()
    await c.message.answer(week_report(c.from_user.id))

@router.callback_query(F.data == "stats:runs")
async def stats_runs(c):
    await c.answer()
    await c.message.answer(runs_report(c.from_user.id))

@router.callback_query(F.data == "stats:records")
async def stats_records(c):
    await c.answer()
    await c.message.answer(records_report(c.from_user.id))

@router.callback_query(F.data == "stats:achievements")
async def stats_ach(c):
    await c.answer()
    await c.message.answer(achievements_report(c.from_user.id))

@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def settings(message):
    await ensure(message)
    u = db.user(message.from_user.id)
    await message.answer(settings_text(message.from_user.id), reply_markup=settings_menu(bool(u["reminders_enabled"])))

@router.callback_query(F.data.startswith("set:"))
async def setting_action(c, state):
    await c.answer()
    field = c.data.split(":",1)[1]
    if field == "toggle_reminders":
        u = db.user(c.from_user.id)
        db.update_setting(c.from_user.id, "reminders_enabled", 0 if u["reminders_enabled"] else 1)
        u = db.user(c.from_user.id)
        await c.message.edit_text(settings_text(c.from_user.id), reply_markup=settings_menu(bool(u["reminders_enabled"])))
        return
    if field == "timezone":
        await c.message.answer("Выбери часовой пояс:", reply_markup=timezone_menu())
        return
    if field == "reminder_times":
        await state.set_state(Flow.reminder_times)
        await c.message.answer("Время через запятую: <code>11:00,16:00,21:00</code>")
        return
    prompts = {
        "pullup_goal": "Сколько подтягиваний в день?",
        "dips_goal": "Сколько брусьев в день?",
        "strength_goal": "Сколько турник + брусья суммарно?",
        "water_goal": "Цель воды в мл?",
        "run_goal_km": "Целевая дистанция в км? Например: 11",
        "run_goal_minutes": "За сколько минут хочешь её пробегать? Например: 60",
    }
    await state.update_data(setting_field=field)
    await state.set_state(Flow.setting_value)
    await c.message.answer(prompts[field])

@router.message(Flow.setting_value)
async def setting_val(message, state):
    data = await state.get_data()
    field = data["setting_field"]
    try:
        if field == "run_goal_km":
            val = float(message.text.replace(",", "."))
            if not 0.1 <= val <= 200: raise ValueError
        else:
            val = int(message.text)
            if val < 0 or val > 20000: raise ValueError
    except Exception:
        await message.answer("Нужно нормальное число.")
        return
    db.update_setting(message.from_user.id, field, val)
    await state.clear()
    await message.answer("✅ Сохранено.", reply_markup=main_menu())

@router.message(Flow.reminder_times)
async def reminder_times(message, state):
    parts = [p for p in message.text.replace(" ","").split(",") if p]
    try:
        for p in parts: datetime.strptime(p, "%H:%M")
        if not parts or len(parts) > 8: raise ValueError
    except Exception:
        await message.answer("Формат: <code>11:00,16:00,21:00</code>")
        return
    db.update_setting(message.from_user.id, "reminder_times", ",".join(parts))
    await state.clear()
    await message.answer("✅ Время сохранено.", reply_markup=main_menu())

@router.callback_query(F.data.startswith("tz:"))
async def timezone_set(c):
    await c.answer()
    zone = c.data.split(":",1)[1]
    ZoneInfo(zone)
    db.update_setting(c.from_user.id, "timezone", zone)
    await c.message.edit_text(f"✅ Часовой пояс: <b>{escape(zone)}</b>")

@router.callback_query(F.data.startswith("act:c"))
async def custom_act(c, state):
    await c.answer()
    aid = int(c.data[5:])
    r = db.custom_by_id(aid)
    if not r:
        await c.message.answer("Не нашёл активность.")
        return
    await state.update_data(custom_activity_id=aid)
    await state.set_state(Flow.custom_activity_amount)
    await c.message.answer(f"{r['emoji']} <b>{escape(r['title'])}</b>\nСколько {escape(r['unit'])}?")

@router.message(Flow.custom_activity_amount)
async def custom_amount(message, state):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
    except Exception:
        await message.answer("Нужно положительное число.")
        return
    data = await state.get_data()
    aid = data["custom_activity_id"]
    r = db.custom_by_id(aid)
    d = get_log_date(message.from_user.id, data)
    db.add_log(message.from_user.id, f"custom_{aid}", amount, d)
    await state.clear()
    await message.answer(f"✅ {r['emoji']} {escape(r['title'])}: +{fmt_num(amount)} {escape(r['unit'])}", reply_markup=main_menu())

def is_admin(uid):
    return cfg.admin_user_id != 0 and uid == cfg.admin_user_id

@router.message(Command("admin"))
@router.message(F.text == "🧰 Админка")
async def admin(message):
    await ensure(message)
    if not is_admin(message.from_user.id):
        await message.answer("Впиши свой ID в ADMIN_USER_ID. Узнать ID: /myid")
        return
    await message.answer(f"<b>🧰 АДМИНКА</b>\nПользователей: <b>{db.users_count()}</b>", reply_markup=admin_menu())

@router.callback_query(F.data == "admin:add")
async def admin_add(c, state):
    await c.answer()
    if not is_admin(c.from_user.id): return
    await state.set_state(Flow.admin_title)
    await c.message.answer("Название активности?")

@router.message(Flow.admin_title)
async def admin_title(message, state):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    title = message.text.strip()
    await state.update_data(admin_title=title)
    await state.set_state(Flow.admin_unit)
    await message.answer("В чём считать?", reply_markup=unit_menu())

@router.callback_query(Flow.admin_unit, F.data.startswith("unit:"))
async def admin_unit(c, state):
    await c.answer()
    data = await state.get_data()
    unit = c.data.split(":",1)[1]
    kind = {"мин":"minutes","км":"distance"}.get(unit,"reps")
    db.add_custom_activity(data["admin_title"], "➕", unit, kind)
    await state.clear()
    await c.message.edit_text(f"✅ Добавил <b>{escape(data['admin_title'])}</b>. Уже есть в меню.")

@router.callback_query(F.data == "admin:home")
async def admin_home(c):
    await c.answer()
    if not is_admin(c.from_user.id):
        return
    await c.message.edit_text(
        f"<b>🧰 АДМИНКА</b>\nПользователей: <b>{db.users_count()}</b>",
        reply_markup=admin_menu(),
    )

@router.callback_query(F.data == "admin:list")
async def admin_list(c):
    await c.answer()
    if not is_admin(c.from_user.id):
        return
    rows = db.all_custom_activities()
    if not rows:
        await c.message.edit_text(
            "Свои активности пока не добавлены.",
            reply_markup=admin_menu(),
        )
        return
    await c.message.edit_text(
        "<b>🛠 УПРАВЛЕНИЕ АКТИВНОСТЯМИ</b>\n\n"
        "🟢 — показывается в «Записать»\n"
        "⚫ — скрыта из «Записать»\n"
        "📊 — показывается в статистике\n"
        "🚫 — скрыта из статистики\n\n"
        "Нажми активность:",
        reply_markup=custom_activity_list_menu(rows),
    )

@router.callback_query(F.data.startswith("admact:open:"))
async def admin_activity_open(c):
    await c.answer()
    if not is_admin(c.from_user.id):
        return
    activity_id = int(c.data.rsplit(":", 1)[1])
    row = db.custom_by_id(activity_id)
    if not row:
        await c.message.edit_text("Активность уже не существует.")
        return
    await c.message.edit_text(
        f"<b>{escape(row['emoji'])} {escape(row['title'])}</b>\n"
        f"Единица: <b>{escape(row['unit'])}</b>\n\n"
        "Скрытие ничего не удаляет из базы. Историю можно вернуть в любой момент.",
        reply_markup=custom_activity_manage_menu(row),
    )

@router.callback_query(F.data.startswith("admact:entry:"))
async def admin_activity_toggle_entry(c):
    await c.answer()
    if not is_admin(c.from_user.id):
        return
    activity_id = int(c.data.rsplit(":", 1)[1])
    row = db.custom_by_id(activity_id)
    if not row:
        return
    db.set_custom_visibility(activity_id, "show_in_entry", not bool(row["show_in_entry"]))
    row = db.custom_by_id(activity_id)
    await c.message.edit_reply_markup(reply_markup=custom_activity_manage_menu(row))

@router.callback_query(F.data.startswith("admact:stats:"))
async def admin_activity_toggle_stats(c):
    await c.answer()
    if not is_admin(c.from_user.id):
        return
    activity_id = int(c.data.rsplit(":", 1)[1])
    row = db.custom_by_id(activity_id)
    if not row:
        return
    db.set_custom_visibility(activity_id, "show_in_stats", not bool(row["show_in_stats"]))
    row = db.custom_by_id(activity_id)
    await c.message.edit_reply_markup(reply_markup=custom_activity_manage_menu(row))



@router.message(F.text == "🗿 Луксмаксинг, ебать")
async def looksmax_start(message, state):
    await ensure(message)
    await state.clear()
    await message.answer(
        "🗿 <b>ЛУКСМАКСИНГ, ЕБАТЬ</b>\n\n"
        "Не магия челюсти из TikTok, а просто трекер того, что ты реально сделал.\n\n"
        "Минимум на день:\n"
        "🧊 Чинтакс — <b>15 повторений</b>\n"
        "🦒 Наклон головы + вытягивание челюсти вверх — <b>60 сек</b>\n"
        "✋ Давить рукой на челюсть — <b>30 повторений</b>",
        reply_markup=looksmax_menu(),
    )


@router.callback_query(F.data.startswith("looks:"))
async def looksmax_action(c, state):
    await c.answer()
    action = c.data.split(":", 1)[1]

    if action == "today":
        progress = looksmax_progress(db, c.from_user.id, db.today(c.from_user.id))
        lines = ["🗿 <b>ЛУКСМАКСИНГ СЕГОДНЯ</b>", ""]
        for item in progress.values():
            lines.append(
                f"{'✅' if item['done'] else '⏳'} {item['title']}: "
                f"<b>{fmt_num(item['total'])}/{item['goal']} {item['unit']}</b>"
            )
        if looksmax_all_done(db, c.from_user.id, db.today(c.from_user.id)):
            lines += ["", "🔥 <b>Минимум закрыт.</b> Челюсть официально не отдана судьбе."]
        await c.message.edit_text("\n".join(lines), reply_markup=looksmax_menu())
        return

    if action not in LOOKSMAX_EXERCISES:
        return

    meta = LOOKSMAX_EXERCISES[action]
    await state.update_data(looksmax_code=action)
    await c.message.edit_text(
        f"🗿 <b>{meta['title']}</b>\n"
        f"Минимум: <b>{meta['goal']} {meta['unit']}</b>\n\n"
        "Сколько сделал сейчас?",
        reply_markup=looksmax_amount_menu(action),
    )


@router.callback_query(F.data.startswith("looksadd:"))
async def looksmax_add(c, state):
    await c.answer()
    _, code, raw = c.data.split(":")
    amount = float(raw)
    meta = LOOKSMAX_EXERCISES[code]
    d = db.today(c.from_user.id)
    db.add_log(c.from_user.id, meta["activity_code"], amount, d)

    progress = looksmax_progress(db, c.from_user.id, d)[code]
    await state.clear()

    await c.message.edit_text(
        f"✅ <b>{meta['title']}: +{fmt_num(amount)} {meta['unit']}</b>\n"
        f"Сегодня: <b>{fmt_num(progress['total'])}/{meta['goal']} {meta['unit']}</b>\n"
        f"{bar(progress['total'], meta['goal'])}\n\n"
        + (
            "🔥 Минимум этого упражнения закрыт."
            if progress["done"]
            else "Пока не минимум. Но уже не ноль, а это мозг любит забывать."
        ),
        reply_markup=looksmax_menu(),
    )


@router.callback_query(F.data.startswith("lookscustom:"))
async def looksmax_custom(c, state):
    await c.answer()
    code = c.data.split(":", 1)[1]
    meta = LOOKSMAX_EXERCISES[code]
    await state.update_data(looksmax_code=code)
    await state.set_state(Flow.looksmax_custom)

    hint = "секунды" if meta["unit"] == "сек" else "повторения"
    await c.message.answer(
        f"Напиши {hint} одним числом для «{meta['title']}»."
    )


@router.message(Flow.looksmax_custom)
async def looksmax_custom_value(message, state):
    data = await state.get_data()
    code = data.get("looksmax_code")
    if code not in LOOKSMAX_EXERCISES:
        await state.clear()
        await message.answer("Контекст потерялся. Открой луксмаксинг заново.")
        return

    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0 or amount > 10000:
            raise ValueError
    except Exception:
        await message.answer("Нужно положительное число.")
        return

    meta = LOOKSMAX_EXERCISES[code]
    d = db.today(message.from_user.id)
    db.add_log(message.from_user.id, meta["activity_code"], amount, d)
    progress = looksmax_progress(db, message.from_user.id, d)[code]
    await state.clear()

    await message.answer(
        f"✅ {meta['title']}: <b>+{fmt_num(amount)} {meta['unit']}</b>\n"
        f"Сегодня: <b>{fmt_num(progress['total'])}/{meta['goal']} {meta['unit']}</b>",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "kbcomplex:start")
async def kb_complex_start(c, state):
    await c.answer()
    old = await state.get_data()
    log_date = old.get("log_date")

    new_data = {
        "kb_complex": True,
        "kb_complex_items": [],
    }
    if log_date:
        new_data["log_date"] = log_date

    await state.set_data(new_data)
    await c.message.edit_text(
        "🧩 Собираем один круг комплекса.\nСначала вес гири:",
        reply_markup=kb_weight(),
    )


@router.callback_query(F.data.startswith("kbcx:"))
async def kb_complex_pick_exercise(c, state):
    await c.answer()
    code = c.data.split(":", 1)[1]

    if code not in BUILTIN:
        return

    await state.update_data(kb_complex_pending=code)
    await state.set_state(Flow.kb_complex_reps)

    await c.message.answer(
        f"{BUILTIN[code]['title']}: сколько повторений <b>в одном круге</b>?"
    )


@router.message(Flow.kb_complex_reps)
async def kb_complex_reps_value(message, state):
    try:
        reps = int(message.text)
        if reps <= 0 or reps > 1000:
            raise ValueError
    except Exception:
        await message.answer("Нужно целое число повторений.")
        return

    data = await state.get_data()
    code = data.get("kb_complex_pending")
    items = list(data.get("kb_complex_items", []))

    items = [x for x in items if x["code"] != code]
    items.append({"code": code, "reps": reps})

    await state.update_data(kb_complex_items=items)
    await state.set_state(None)

    summary = "\n".join(
        f"• {BUILTIN[x['code']]['title']}: {x['reps']}"
        for x in items
    )

    await message.answer(
        "<b>Один круг сейчас:</b>\n"
        + summary
        + "\n\nДобавить ещё упражнение или круг готов?",
        reply_markup=kb_complex_controls(),
    )


@router.callback_query(F.data == "kbc:add")
async def kb_complex_add_more(c):
    await c.answer()
    await c.message.edit_text(
        "Что ещё в круг?",
        reply_markup=kb_complex_exercises(),
    )


@router.callback_query(F.data == "kbc:finish")
async def kb_complex_finish(c, state):
    await c.answer()
    data = await state.get_data()

    if not data.get("kb_complex_items"):
        await c.message.answer("Сначала добавь упражнения в круг.")
        return

    await c.message.edit_text(
        "Сколько одинаковых кругов сделал?",
        reply_markup=kb_complex_rounds(),
    )


@router.callback_query(F.data.startswith("kbround:"))
async def kb_complex_rounds_pick(c, state):
    await c.answer()
    val = c.data.split(":", 1)[1]

    if val == "custom":
        await state.set_state(Flow.kb_complex_rounds)
        await c.message.answer("Сколько кругов? Одно число.")
        return

    await save_kb_complex(c, state, int(val))


@router.message(Flow.kb_complex_rounds)
async def kb_complex_rounds_custom(message, state):
    try:
        rounds = int(message.text)
        if rounds <= 0 or rounds > 100:
            raise ValueError
    except Exception:
        await message.answer("Нужно целое количество кругов.")
        return

    await save_kb_complex(message, state, rounds)


async def save_kb_complex(event, state, rounds):
    data = await state.get_data()
    user_id = event.from_user.id
    d = get_log_date(user_id, data)
    weight = float(data["kb_weight"])
    items = data.get("kb_complex_items", [])

    add_kb_complex(
        db,
        user_id,
        d,
        weight,
        rounds,
        items,
    )

    first = db.unlock(user_id, "kb_complex_first")
    codes = ["kb_complex_first"] if first else []
    total = sum(int(x["reps"]) for x in items) * rounds

    lines = [
        f"✅ <b>ГИРЕВОЙ КОМПЛЕКС · {rounds} круга</b>",
        f"🟠 Вес: <b>{fmt_num(weight)} кг</b>",
        f"🔢 Всего повторений: <b>{total}</b>",
        "",
    ]

    for x in items:
        lines.append(
            f"• {BUILTIN[x['code']]['title']}: "
            f"{x['reps']} × {rounds} = <b>{x['reps'] * rounds}</b>"
        )

    await state.clear()

    target = event.message if hasattr(event, "message") else event
    await target.answer(
        "\n".join(lines) + await achievement_text(codes),
        reply_markup=main_menu(),
    )

    await send_codes_media(
        event.bot,
        target.chat.id,
        codes,
    )


def strength_history_report(user_id):
    pull = pr_history(db, user_id, "pullup")
    dips = pr_history(db, user_id, "dips")
    days = strength_recent_days(db, user_id, 14)

    lines = [
        "<b>📜 ИСТОРИЯ СИЛЫ</b>",
        "",
        "🧗 <b>PR турник:</b>",
    ]

    if pull:
        for r in pull[-10:]:
            delta = (
                f" (+{fmt_num(r['delta'])})"
                if r["delta"] is not None
                else " (старт)"
            )
            lines.append(
                f"• {r['date']} · <b>{fmt_num(r['value'])}</b>{delta}"
            )
    else:
        lines.append("• пока пусто")

    lines += ["", "💪 <b>PR брусья:</b>"]

    if dips:
        for r in dips[-10:]:
            delta = (
                f" (+{fmt_num(r['delta'])})"
                if r["delta"] is not None
                else " (старт)"
            )
            lines.append(
                f"• {r['date']} · <b>{fmt_num(r['value'])}</b>{delta}"
            )
    else:
        lines.append("• пока пусто")

    lines += [
        "",
        "<b>Последние 14 дней · всего / лучший подход:</b>",
    ]

    any_days = False
    for r in days:
        if any(
            (
                r["pull_total"],
                r["dips_total"],
            )
        ):
            any_days = True
            lines.append(
                f"• {r['date'][5:]}  "
                f"🧗 {fmt_num(r['pull_total'])}/{fmt_num(r['pull_max'])}  "
                f"💪 {fmt_num(r['dips_total'])}/{fmt_num(r['dips_max'])}"
            )

    if not any_days:
        lines.append("• пока нечего показывать")

    return "\n".join(lines)


def global_report(user_id):
    s = global_stats(db, user_id)

    base = (
        "<b>🧮 ОБЩАЯ СТАТИСТИКА</b>\n\n"
        f"🔥 Всего турник + брусья: <b>{fmt_num(s['strength'])}</b>\n"
        f"🧗 Подтягиваний: <b>{fmt_num(s['pull'])}</b>\n"
        f"💪 Брусьев: <b>{fmt_num(s['dips'])}</b>\n"
        f"🟠 Повторений с гирей: <b>{fmt_num(s['kb_reps'])}</b>\n"
        f"🧩 Гиревых комплексов: <b>{s['kb_sessions']}</b>\n\n"
        f"🏃 Бега: <b>{fmt_num(s['run_km'])} км</b> за {s['run_count']} пробежек\n"
        f"⏱ Времени бегом: <b>{fmt_duration(s['run_sec']) if s['run_sec'] else '—'}</b>\n"
        f"💧 Воды записано: <b>{s['water_l']:.1f} л</b>\n"
        f"🙂 Сессий для лица: <b>{s['face_sessions']}</b>\n\n"
        f"🔥 Текущая серия минимума: <b>{s['current_streak']} дней</b>\n"
        f"🏆 Лучшая серия: <b>{s['best_streak']} дней</b>\n"
        f"📆 Дней с любой записанной активностью: <b>{s['active_days']}</b>"
    )
    custom_rows = db.custom_totals(user_id)
    if custom_rows:
        custom_text = ["", "➕ <b>Свои активности за всё время:</b>"]
        for row in custom_rows:
            custom_text.append(
                f"• {escape(row['emoji'])} {escape(row['title'])}: "
                f"<b>{fmt_num(row['total'])} {escape(row['unit'])}</b>"
            )
        base += "\n" + "\n".join(custom_text)
    return base


def kb_complex_report(user_id):
    rows = recent_kb_complexes(db, user_id, 6)

    if not rows:
        return (
            "🟠 Комплексов пока нет. "
            "Собери первый через «Гиря → Собрать комплекс»."
        )

    lines = [
        "<b>🟠 ПОСЛЕДНИЕ КОМПЛЕКСЫ</b>",
        "",
    ]

    for r in rows:
        parts = ", ".join(
            f"{BUILTIN[x['code']]['title'].replace('Гиря · ', '')} {x['reps']}"
            for x in r["items"]
        )
        lines.append(
            f"• {r['date']} · {fmt_num(r['weight'])} кг · "
            f"{r['rounds']} кр. · {escape(parts)}"
        )

    return "\n".join(lines)


@router.callback_query(F.data == "stats:strength")
async def stats_strength(c):
    await c.answer()
    await c.message.answer(strength_history_report(c.from_user.id))


@router.callback_query(F.data == "stats:global")
async def stats_global(c):
    await c.answer()
    await c.message.answer(global_report(c.from_user.id))


@router.callback_query(F.data == "stats:kbcomplex")
async def stats_kbcomplex(c):
    await c.answer()
    await c.message.answer(kb_complex_report(c.from_user.id))


@router.callback_query(F.data == "close")
async def close(c):
    await c.answer()
    try: await c.message.delete()
    except Exception: pass

async def reminder_loop(bot):
    while True:
        try:
            for u in db.users_for_reminders():
                try:
                    tz = ZoneInfo(u["timezone"])
                except Exception:
                    try:
                        tz = ZoneInfo(cfg.default_timezone)
                    except Exception:
                        tz = timezone(timedelta(hours=3))
                now = datetime.now(tz)
                d = now.date().isoformat()
                for reminder_time in [x for x in u["reminder_times"].split(",") if x]:
                    try:
                        hh, mm = map(int, reminder_time.split(":"))
                        scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    except Exception:
                        continue
                    if not (scheduled <= now < scheduled + timedelta(minutes=10)): continue
                    if db.reminder_already_sent(u["user_id"], d, reminder_time): continue

                    s = db.daily(u["user_id"], d)
                    pull, dips = activity_total(s, "pullup"), activity_total(s, "dips")
                    strength = pull + dips
                    rp = max(0, u["pullup_goal"]-pull)
                    rd = max(0, u["dips_goal"]-dips)
                    rs = max(0, u["strength_goal"]-strength)
                    looks = looksmax_progress(db, u["user_id"], d)
                    looks_remaining = [
                        item for item in looks.values()
                        if not item["done"]
                    ]

                    if rp <= 0 and rd <= 0 and rs <= 0 and not looks_remaining:
                        db.mark_reminder_sent(u["user_id"], d, reminder_time)
                        continue

                    bits = []
                    if rp > 0: bits.append(f"🧗 турник: ещё {int(rp)}")
                    if rd > 0: bits.append(f"💪 брусья: ещё {int(rd)}")
                    if rs > 0:
                        bits.append(f"🔥 общий минимум: ещё {int(rs)}")
                    for item in looks_remaining:
                        remain = max(0, float(item["goal"]) - float(item["total"]))
                        bits.append(
                            f"🗿 {item['title']}: ещё {fmt_num(remain)} {item['unit']}"
                        )

                    msg = (
                        "<b>⏰ ПРАЙМ-НАДЗОР</b>\n\n"
                        + random.choice(REMINDERS)
                        + "\n\n"
                        + "\n".join(bits)
                    )
                    try:
                        await bot.send_message(u["user_id"], msg, reply_markup=main_menu())
                        db.mark_reminder_sent(u["user_id"], d, reminder_time)
                    except Exception:
                        logging.exception("Reminder failed")
        except Exception:
            logging.exception("Reminder loop failure")
        await asyncio.sleep(30)

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    task = asyncio.create_task(reminder_loop(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
