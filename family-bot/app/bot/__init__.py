from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from ..config import settings
from .handlers import router

_bot: Bot | None = None
_dispatcher: Dispatcher | None = None

COMMANDS = [
    BotCommand(command="app", description="Открыть приложение"),
    BotCommand(command="lists", description="Категории покупок"),
    BotCommand(command="wish", description="Вишлисты"),
    BotCommand(command="share", description="Ссылки для друзей"),
    BotCommand(command="expenses", description="Последние траты"),
    BotCommand(command="stats", description="Сводка за месяц"),
    BotCommand(command="invite", description="Пригласить в семью"),
    BotCommand(command="help", description="Справка"),
]


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not settings.bot_token:
            raise RuntimeError("BOT_TOKEN не задан — заполни .env")
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(router)
    return _dispatcher


__all__ = ["COMMANDS", "get_bot", "get_dispatcher", "router"]
