"""Ежедневная проверка: не подошёл ли срок регулярного платежа."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..config import settings
from ..db import SessionLocal
from ..models import PERIODS
from ..services.recurring import due_state, templates_due
from ..services.users import household_members

log = logging.getLogger(__name__)

CHECK_INTERVAL = 15 * 60  # раз в 15 минут смотрим, не пора ли
_last_run: dt.date | None = None


def local_now() -> dt.datetime:
    try:
        return dt.datetime.now(ZoneInfo(settings.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Не знаю часовой пояс %s, беру время системы", settings.timezone)
        return dt.datetime.now()


def payment_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оплатили", callback_data=f"exp:paid:{expense_id}"),
                InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"exp:skip:{expense_id}"),
            ]
        ]
    )


def reminder_text(template, days: int, caption: str) -> str:
    emoji = template.category.emoji if template.category else "🔁"
    title = template.title or (template.category.title if template.category else "Платёж")
    amount = f"{float(template.amount):,.2f}".replace(",", " ").replace(".00", "")
    head = "🔔 <b>Скоро платёж</b>" if days >= 0 else "⚠️ <b>Платёж просрочен</b>"
    return (
        f"{head}\n\n"
        f"{emoji} {escape(title)} — <b>{amount} {escape(template.currency)}</b>\n"
        f"📅 {template.next_due_on.strftime('%d.%m.%Y')} ({caption})\n"
        f"🔁 {PERIODS.get(template.period, template.period)}"
    )


async def send_due_reminders(bot: Bot, today: dt.date | None = None) -> int:
    """Один проход напоминаний. Возвращает, сколько платежей разослали."""
    today = today or local_now().date()
    sent = 0

    async with SessionLocal() as session:
        templates = await templates_due(session, settings.remind_days_before, today=today)
        members_cache: dict[int, list] = {}

        for template in templates:
            if template.household_id not in members_cache:
                members_cache[template.household_id] = await household_members(
                    session, template.household_id
                )
            days, caption = due_state(template, today=today)
            text = reminder_text(template, days, caption)

            delivered = False
            for member in members_cache[template.household_id]:
                try:
                    await bot.send_message(
                        member.tg_id, text, reply_markup=payment_keyboard(template.id)
                    )
                    delivered = True
                except TelegramAPIError as error:
                    # Человек мог заблокировать бота — это не повод ронять рассылку.
                    log.warning("Не доставила напоминание %s: %s", member.tg_id, error)

            if delivered:
                template.last_reminded_on = today
                sent += 1

        await session.commit()

    return sent


async def reminder_loop(bot: Bot) -> None:
    """Раз в 15 минут проверяет, наступил ли час напоминаний в этот день.

    Ноутбук мог спать в назначенное время — тогда напомним при первом же
    просыпании после нужного часа, а не пропустим день целиком.
    """
    global _last_run
    while True:
        try:
            now = local_now()
            if now.hour >= settings.reminder_hour and _last_run != now.date():
                count = await send_due_reminders(bot, today=now.date())
                _last_run = now.date()
                if count:
                    log.info("Разослала напоминаний о платежах: %s", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(CHECK_INTERVAL)
