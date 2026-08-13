"""Рассылка при смене адреса приложения.

Кнопка «Открыть приложение» несёт в себе конкретный URL и остаётся в чате
навсегда. Бесплатный туннель выдаёт новый адрес при каждом запуске, поэтому
старые кнопки ведут в никуда — браузер показывает «не удалось найти IP-адрес».
Чтобы не гадать, при старте с новым адресом отправляем всем свежее меню.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import User
from ..services.state import get_state, set_state
from . import keyboards as kb

log = logging.getLogger(__name__)

STATE_KEY = "public_url"

TEXT = (
    "🔗 <b>Адрес приложения обновился</b>\n\n"
    "Старые кнопки «Открыть приложение» из прошлых сообщений больше не работают — "
    "нажимай кнопку внизу экрана, она уже новая.\n\n"
    "⚠️ Ссылки на вишлисты, которыми ты делилась раньше, тоже сменились: "
    "отправь друзьям новые через /share."
)


async def announce_new_address(bot: Bot) -> int:
    """Если адрес сменился с прошлого запуска — обновляем у всех меню."""
    current = settings.base_url

    async with SessionLocal() as session:
        previous = await get_state(session, STATE_KEY)
        if previous == current:
            return 0
        await set_state(session, STATE_KEY, current)
        if not previous:
            return 0  # первый запуск — рассылать нечего
        users = list(await session.scalars(select(User)))

    notified = 0
    for user in users:
        try:
            await bot.send_message(user.tg_id, TEXT, reply_markup=kb.main_menu())
            notified += 1
        except TelegramAPIError as error:
            log.warning("Не смогла сообщить новый адрес %s: %s", user.tg_id, error)

    if notified:
        log.info("Сообщила о новом адресе %s: %s чел.", current, notified)
    return notified
