from __future__ import annotations

import random
from pathlib import Path
from aiogram.types import FSInputFile

MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"

RECORD_IMAGES = [
    "flaming_skull.png",
    "back_in_line.png",
    "american_psycho_fire.png",
    "knight_ok.png",
    "legend.png",
    "lion_energy.png",
]
SETBACK_IMAGES = [
    "tomorrow_try_again.png",
    "cringe_wizard.png",
]
ACHIEVEMENT_IMAGES = [
    "masked_suit.png",
    "legend.png",
    "doebat_mne.png",
    "flaming_skull.png",
]

async def _send_photo(bot, chat_id, filename, caption=None):
    path = MEDIA_DIR / filename
    if not path.exists():
        return False
    await bot.send_photo(chat_id, FSInputFile(path), caption=caption)
    return True

async def send_record_media(bot, chat_id):
    await _send_photo(
        bot,
        chat_id,
        random.choice(RECORD_IMAGES),
        "PR. Цифры официально стали наглее.",
    )

async def send_setback_media(bot, chat_id):
    await _send_photo(bot, chat_id, random.choice(SETBACK_IMAGES))

async def send_achievement_media(bot, chat_id, major=False):
    video = MEDIA_DIR / "achievement.mp4"
    audio = MEDIA_DIR / "achievement_track.mp3"

    roll = random.random()
    if major and video.exists() and roll < 0.45:
        await bot.send_video(
            chat_id,
            FSInputFile(video),
            caption="🎖 Ачивка разблокирована. Дешёвого дофамина заслужил.",
        )
        return

    if major and audio.exists() and roll < 0.70:
        await bot.send_audio(
            chat_id,
            FSInputFile(audio),
            caption="🎖 Саундтрек к маленькой победе.",
        )
        return

    await _send_photo(bot, chat_id, random.choice(ACHIEVEMENT_IMAGES))

async def send_yoga_media(bot, chat_id):
    path = MEDIA_DIR / "meditation.mp4"
    if path.exists():
        await bot.send_video(
            chat_id,
            FSInputFile(path),
            caption="🧘 Медитация теперь только такая.",
        )
