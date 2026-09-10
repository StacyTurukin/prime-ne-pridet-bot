from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏋️ Записать"), KeyboardButton(text="💧 Вода")],
            [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📈 Статистика")],
            [KeyboardButton(text="🗓 Задним числом"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🗿 Луксмаксинг, ебать"), KeyboardButton(text="🧰 Админка")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Прайм не придёт, если просто ждать",
    )

def activity_menu(custom_rows=None):
    rows = [
        [InlineKeyboardButton(text="🧗 Турник", callback_data="act:pullup"),
         InlineKeyboardButton(text="💪 Брусья", callback_data="act:dips")],
        [InlineKeyboardButton(text="🟠 Гиря", callback_data="act:kb"),
         InlineKeyboardButton(text="🧘 Йога", callback_data="act:yoga")],
        [InlineKeyboardButton(text="🏃 Бег", callback_data="act:run")],
    ]
    if custom_rows:
        for r in custom_rows:
            rows.append([InlineKeyboardButton(text=f"{r['emoji']} {r['title']}", callback_data=f"act:c{r['id']}")])
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def reps_menu(code):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(v), callback_data=f"reps:{code}:{v}") for v in (5,10,15)],
        [InlineKeyboardButton(text=str(v), callback_data=f"reps:{code}:{v}") for v in (20,25,30)],
        [InlineKeyboardButton(text="✍️ Другое", callback_data=f"repscustom:{code}")],
    ])

def yoga_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v} мин", callback_data=f"yoga:{v}") for v in (10,20,30)],
        [InlineKeyboardButton(text=f"{v} мин", callback_data=f"yoga:{v}") for v in (45,60)],
        [InlineKeyboardButton(text="✍️ Другое", callback_data="yogacustom")],
    ])

def kb_exercises():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Махи", callback_data="kbex:kb_swing"),
         InlineKeyboardButton(text="Рывок", callback_data="kbex:kb_snatch")],
        [InlineKeyboardButton(text="Взятие + жим", callback_data="kbex:kb_clean_press")],
        [InlineKeyboardButton(text="Goblet-присед", callback_data="kbex:kb_goblet")],
        [InlineKeyboardButton(text="Турецкий подъём", callback_data="kbex:kb_tgu")],
        [InlineKeyboardButton(text="🧩 Собрать комплекс", callback_data="kbcomplex:start")],
    ])

def kb_weight():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v} кг", callback_data=f"kbw:{v}") for v in (8,12,16)],
        [InlineKeyboardButton(text=f"{v} кг", callback_data=f"kbw:{v}") for v in (20,24,32)],
        [InlineKeyboardButton(text="✍️ Другой вес", callback_data="kbwcustom")],
    ])

def kb_reps():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(v), callback_data=f"kbr:{v}") for v in (10,20,30,50)],
        [InlineKeyboardButton(text="✍️ Другое", callback_data="kbrcustom")],
    ])

def water_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"+{v} мл", callback_data=f"water:{v}") for v in (150,250,330)],
        [InlineKeyboardButton(text=f"+{v} мл", callback_data=f"water:{v}") for v in (500,750)],
        [InlineKeyboardButton(text="✍️ Другое", callback_data="watercustom")],
    ])

def run_place_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏟 Стадион", callback_data="runplace:Стадион"),
         InlineKeyboardButton(text="🏫 Техникум", callback_data="runplace:Техникум")],
        [InlineKeyboardButton(text="🌲 Трейл", callback_data="runplace:Трейлраннинг"),
         InlineKeyboardButton(text="📍 Другое", callback_data="runplace:Другое")],
    ])

def run_distance_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v} км", callback_data=f"rundist:{v}") for v in (5,8,10)],
        [InlineKeyboardButton(text=f"{v} км", callback_data=f"rundist:{v}") for v in (11,12,15)],
        [InlineKeyboardButton(text="✍️ Другая", callback_data="rundist:custom")],
    ])

def run_hardness_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 😎", callback_data="runhard:1"),
         InlineKeyboardButton(text="2 🙂", callback_data="runhard:2"),
         InlineKeyboardButton(text="3 😤", callback_data="runhard:3")],
        [InlineKeyboardButton(text="4 🥵", callback_data="runhard:4"),
         InlineKeyboardButton(text="5 ☠️", callback_data="runhard:5")],
    ])

def stats_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Сегодня", callback_data="stats:today"),
         InlineKeyboardButton(text="🗓 7 дней", callback_data="stats:week")],
        [InlineKeyboardButton(text="🏃 Бег", callback_data="stats:runs"),
         InlineKeyboardButton(text="🏆 Рекорды", callback_data="stats:records")],
        [InlineKeyboardButton(text="📜 История PR", callback_data="stats:strength"),
         InlineKeyboardButton(text="🧮 Общая", callback_data="stats:global")],
        [InlineKeyboardButton(text="🟠 Комплексы", callback_data="stats:kbcomplex"),
         InlineKeyboardButton(text="🎖 Ачивки", callback_data="stats:achievements")],
    ])

def backdate_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Вчера", callback_data="backdate:1"),
         InlineKeyboardButton(text="Позавчера", callback_data="backdate:2")],
        [InlineKeyboardButton(text="3 дня назад", callback_data="backdate:3"),
         InlineKeyboardButton(text="7 дней назад", callback_data="backdate:7")],
        [InlineKeyboardButton(text="✍️ Своя дата", callback_data="backdate:custom")],
    ])

def settings_menu(enabled):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧗 Минимум турник", callback_data="set:pullup_goal")],
        [InlineKeyboardButton(text="💪 Минимум брусья", callback_data="set:dips_goal")],
        [InlineKeyboardButton(text="🔥 Общий минимум", callback_data="set:strength_goal")],
        [InlineKeyboardButton(text="💧 Цель воды", callback_data="set:water_goal")],
        [InlineKeyboardButton(text="🏃 Цель дистанции", callback_data="set:run_goal_km"),
         InlineKeyboardButton(text="⏱ Цель времени", callback_data="set:run_goal_minutes")],
        [InlineKeyboardButton(text="⏰ Время напоминаний", callback_data="set:reminder_times")],
        [InlineKeyboardButton(text=("🔕 Выключить напоминания" if enabled else "🔔 Включить напоминания"), callback_data="set:toggle_reminders")],
        [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="set:timezone")],
    ])

def timezone_menu():
    zones = [
        ("Москва", "Europe/Moscow"), ("Калининград", "Europe/Kaliningrad"),
        ("Екатеринбург", "Asia/Yekaterinburg"), ("Новосибирск", "Asia/Novosibirsk"),
        ("Владивосток", "Asia/Vladivostok"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"tz:{zone}")] for name, zone in zones
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить активность", callback_data="admin:add")],
        [InlineKeyboardButton(text="🛠 Управление активностями", callback_data="admin:list")],
    ])

def unit_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="повт.", callback_data="unit:повт.")],
        [InlineKeyboardButton(text="мин", callback_data="unit:мин")],
        [InlineKeyboardButton(text="км", callback_data="unit:км")],
        [InlineKeyboardButton(text="подходов", callback_data="unit:подходов")],
    ])


def kb_complex_exercises():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Махи", callback_data="kbcx:kb_swing"),
         InlineKeyboardButton(text="Рывок", callback_data="kbcx:kb_snatch")],
        [InlineKeyboardButton(text="Взятие + жим", callback_data="kbcx:kb_clean_press")],
        [InlineKeyboardButton(text="Goblet-присед", callback_data="kbcx:kb_goblet")],
        [InlineKeyboardButton(text="Турецкий подъём", callback_data="kbcx:kb_tgu")],
    ])

def kb_complex_controls():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё упражнение", callback_data="kbc:add")],
        [InlineKeyboardButton(text="✅ Круг собран", callback_data="kbc:finish")],
    ])

def kb_complex_rounds():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2 круга", callback_data="kbround:2"),
         InlineKeyboardButton(text="3 круга", callback_data="kbround:3")],
        [InlineKeyboardButton(text="4 круга", callback_data="kbround:4"),
         InlineKeyboardButton(text="5 кругов", callback_data="kbround:5")],
        [InlineKeyboardButton(text="✍️ Другое", callback_data="kbround:custom")],
    ])

def face_menu(selected=None):
    selected = set(selected or [])
    items = [
        ("forehead", "Лоб"),
        ("eyes", "Глаза"),
        ("cheeks", "Щёки"),
        ("oval", "Овал + шея"),
        ("massage", "Массаж"),
    ]
    rows = []
    for code, title in items:
        mark = "✅" if code in selected else "▫️"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {title}",
                callback_data=f"face:{code}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔥 Записать выбранное",
            callback_data="face:save",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def looksmax_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧊 Чинтакс", callback_data="looks:chintucks")],
        [InlineKeyboardButton(text="🦒 Челюсть вверх", callback_data="looks:jaw_up")],
        [InlineKeyboardButton(text="✋ Давить челюсть", callback_data="looks:jaw_press")],
        [InlineKeyboardButton(text="📊 Прогресс сегодня", callback_data="looks:today")],
    ])

def looksmax_amount_menu(code):
    presets = {
        "chintucks": [5, 10, 15, 20, 30],
        "jaw_up": [30, 60, 90, 120],
        "jaw_press": [10, 20, 30, 40, 50],
    }
    suffix = " сек" if code == "jaw_up" else ""
    vals = presets[code]
    rows = []
    first = vals[:3]
    second = vals[3:]
    rows.append([
        InlineKeyboardButton(
            text=f"{v}{suffix}",
            callback_data=f"looksadd:{code}:{v}",
        ) for v in first
    ])
    if second:
        rows.append([
            InlineKeyboardButton(
                text=f"{v}{suffix}",
                callback_data=f"looksadd:{code}:{v}",
            ) for v in second
        ])
    rows.append([
        InlineKeyboardButton(
            text="✍️ Другое",
            callback_data=f"lookscustom:{code}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_activity_manage_menu(row):
    entry_on = bool(row["show_in_entry"])
    stats_on = bool(row["show_in_stats"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=("📝 В записи: ВКЛ" if entry_on else "📝 В записи: СКРЫТА"),
            callback_data=f"admact:entry:{row['id']}",
        )],
        [InlineKeyboardButton(
            text=("📊 В статистике: ВКЛ" if stats_on else "📊 В статистике: СКРЫТА"),
            callback_data=f"admact:stats:{row['id']}",
        )],
        [InlineKeyboardButton(text="↩️ К списку", callback_data="admin:list")],
    ])

def custom_activity_list_menu(rows):
    buttons = []
    for row in rows:
        entry = "🟢" if row["show_in_entry"] else "⚫"
        stats = "📊" if row["show_in_stats"] else "🚫"
        buttons.append([InlineKeyboardButton(
            text=f"{entry}{stats} {row['title']}",
            callback_data=f"admact:open:{row['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="↩️ Админка", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
