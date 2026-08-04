from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from ..config import settings
from ..models import ExpenseCategory, ItemList


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Открыть приложение", web_app=WebAppInfo(url=settings.webapp_url))],
            [KeyboardButton(text="📋 Списки"), KeyboardButton(text="🎁 Вишлисты")],
            [KeyboardButton(text="💸 Траты"), KeyboardButton(text="📊 За месяц")],
        ],
        resize_keyboard=True,
    )


def open_app_button(text: str = "🛍 Открыть приложение") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))]]
    )


def item_actions(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Другая категория", callback_data=f"item:pick:{item_id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"item:del:{item_id}"),
            ],
            [InlineKeyboardButton(text="✅ Уже купили", callback_data=f"item:buy:{item_id}")],
        ]
    )


def list_picker(item_id: int, lists: list[ItemList]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for item_list in lists:
        row.append(
            InlineKeyboardButton(
                text=f"{item_list.emoji} {item_list.title}",
                callback_data=f"item:move:{item_id}:{item_list.id}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"item:back:{item_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def expense_actions(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Категория", callback_data=f"exp:pick:{expense_id}"),
                InlineKeyboardButton(text="🔁 Периодичность", callback_data=f"exp:period:{expense_id}"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"exp:del:{expense_id}")],
        ]
    )


def expense_category_picker(
    expense_id: int, categories: list[ExpenseCategory]
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for category in categories:
        row.append(
            InlineKeyboardButton(
                text=f"{category.emoji} {category.title}",
                callback_data=f"exp:set:{expense_id}:{category.id}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"exp:back:{expense_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def period_picker(expense_id: int) -> InlineKeyboardMarkup:
    options = [
        ("Разовая", "once"),
        ("Ежемесячная", "monthly"),
        ("Ежеквартальная", "quarterly"),
        ("Ежегодная", "yearly"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"exp:setperiod:{expense_id}:{key}")]
            for title, key in options
        ]
        + [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"exp:back:{expense_id}")]]
    )


def share_link_button(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть список", url=url)]]
    )
