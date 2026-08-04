from __future__ import annotations

import datetime as dt
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..db import SessionLocal
from ..models import PERIODS, Expense, ExpenseCategory, Household, Item, ItemList, User
from ..services import items as items_service
from ..services.link_parser import extract_urls
from ..services.quick_expense import parse_expense
from ..services.users import get_or_create_user, join_household
from . import keyboards as kb

router = Router()

HELP = """<b>Что я умею</b>

🔗 <b>Пришли ссылку на товар</b> — сам вытяну название, цену и картинку
и положу в подходящую категорию (техника, кухня, квартира, текстиль, baby…).
Категорию всегда можно поменять кнопкой под сообщением.

💸 <b>Напиши сумму</b> — «450 бензин» или «1200 грн аптека ежемесячная».
Определю категорию траты и запишу.

🎁 <b>Вишлисты</b> — общий на двоих и личный у каждого.
Любой список можно открыть по ссылке: гости увидят его без Telegram
и смогут отметить «Забронировано», чтобы не задарить одно и то же дважды.

<b>Команды</b>
/app — открыть приложение
/lists — категории покупок
/wish — вишлисты
/share — ссылки для друзей
/spend — как записывать траты
/stats — сводка за месяц
/invite — позвать мужа/жену в общее пространство
/help — эта справка"""

SPEND_HELP = """<b>Как записывать траты</b>

Просто отправь сообщение:
• <code>450 бензин</code>
• <code>1200 грн аптека</code>
• <code>90 usd страховка машины ежегодная</code>
• <code>-350 продукты</code>

Слова «ежемесячная», «ежеквартальная», «ежегодная» ставят периодичность.
Категорию подберу сам, поправить можно кнопкой под сообщением."""


async def resolve_user(session: AsyncSession, message: Message | CallbackQuery) -> User:
    tg_user = message.from_user
    return await get_or_create_user(
        session,
        tg_id=tg_user.id,
        first_name=tg_user.first_name or "",
        username=tg_user.username,
        language_code=tg_user.language_code,
    )


def money(amount, currency: str | None) -> str:
    if amount is None:
        return ""
    return f"{float(amount):,.2f}".replace(",", " ").replace(".00", "") + (f" {currency}" if currency else "")


def item_card(item: Item, item_list: ItemList) -> str:
    lines = [f"✅ Добавила в <b>{escape(item_list.emoji)} {escape(item_list.title)}</b>", ""]
    lines.append(f"<b>{escape(item.title)}</b>")
    if item.price:
        lines.append(f"💰 {money(item.price, item.currency or settings.default_currency)}")
    if item.shop:
        lines.append(f"🏬 {escape(item.shop)}")
    if item.url:
        lines.append(f'<a href="{escape(item.url)}">Ссылка на товар</a>')
    return "\n".join(lines)


def expense_card(expense: Expense) -> str:
    category = expense.category
    lines = [
        f"💸 Записала: <b>{money(expense.amount, expense.currency)}</b>",
        f"📂 {category.emoji + ' ' + escape(category.title) if category else 'Без категории'}",
    ]
    if expense.title:
        lines.append(f"📝 {escape(expense.title)}")
    if expense.period != "once":
        lines.append(f"🔁 {PERIODS[expense.period]}")
    lines.append(f"📅 {expense.spent_on.strftime('%d.%m.%Y')}")
    return "\n".join(lines)


@router.message(CommandStart(deep_link=True))
async def start_with_payload(message: Message, command: CommandObject) -> None:
    payload = (command.args or "").strip()
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        if payload.startswith("join_"):
            household = await join_household(session, user, payload[5:])
            if household is None:
                await message.answer("Не нашла такое приглашение 🤔", reply_markup=kb.main_menu())
                return
            await message.answer(
                f"Готово! Теперь ты в пространстве «{escape(household.title)}» — "
                "списки и траты общие.",
                reply_markup=kb.main_menu(),
            )
            return
    await start(message)


@router.message(CommandStart())
async def start(message: Message) -> None:
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
    await message.answer(
        f"Привет, {escape(user.display_name)}! 👋\n\n"
        "Я держу ваши списки покупок, вишлисты и траты в одном месте.\n"
        "Кинь мне ссылку на товар или сумму траты — остальное сделаю сама.",
        reply_markup=kb.main_menu(),
    )
    await message.answer(HELP, reply_markup=kb.open_app_button(), disable_web_page_preview=True)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP, reply_markup=kb.open_app_button(), disable_web_page_preview=True)


@router.message(Command("spend"))
async def spend_help(message: Message) -> None:
    await message.answer(SPEND_HELP)


@router.message(Command("app"))
@router.message(F.text == "🛍 Открыть приложение")
async def open_app(message: Message) -> None:
    await message.answer("Приложение здесь 👇", reply_markup=kb.open_app_button())


@router.message(Command("invite"))
async def invite(message: Message) -> None:
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        household = await session.get(Household, user.household_id)
    from .. import runtime

    link = runtime.invite_link(household.invite_code)
    await message.answer(
        "Отправь эту ссылку второй половинке — и списки станут общими:\n\n"
        f"{escape(link)}",
        disable_web_page_preview=True,
    )


@router.message(Command("lists"))
@router.message(F.text == "📋 Списки")
async def show_lists(message: Message) -> None:
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        rows = await session.execute(
            select(ItemList, func.count(Item.id))
            .outerjoin(Item, (Item.list_id == ItemList.id) & (Item.status == "active"))
            .where(ItemList.household_id == user.household_id, ItemList.kind == "shopping")
            .group_by(ItemList.id)
            .order_by(ItemList.position, ItemList.id)
        )
        lines = ["<b>📋 Категории покупок</b>", ""]
        for item_list, count in rows:
            share = " 🔗" if item_list.is_shared else ""
            lines.append(f"{item_list.emoji} {escape(item_list.title)} — {count}{share}")
    await message.answer("\n".join(lines), reply_markup=kb.open_app_button("Открыть списки"))


@router.message(Command("wish"))
@router.message(F.text == "🎁 Вишлисты")
async def show_wishlists(message: Message) -> None:
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        rows = await session.execute(
            select(ItemList, func.count(Item.id))
            .outerjoin(Item, (Item.list_id == ItemList.id) & (Item.status == "active"))
            .where(ItemList.household_id == user.household_id, ItemList.kind == "wishlist")
            .group_by(ItemList.id)
            .order_by(ItemList.position, ItemList.id)
        )
        lines = ["<b>🎁 Вишлисты</b>", ""]
        for item_list, count in rows:
            lines.append(f"{item_list.emoji} {escape(item_list.title)} — {count}")
            if item_list.is_shared:
                lines.append(f"   🔗 {settings.share_url(item_list.share_token)}")
        lines += ["", "Поделиться списком: /share"]
    await message.answer(
        "\n".join(lines),
        reply_markup=kb.open_app_button("Открыть вишлисты"),
        disable_web_page_preview=True,
    )


@router.message(Command("share"))
async def share_menu(message: Message) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        lists = list(
            await session.scalars(
                select(ItemList)
                .where(ItemList.household_id == user.household_id)
                .order_by(ItemList.kind, ItemList.position, ItemList.id)
            )
        )
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'🔗' if item_list.is_shared else '🔒'} {item_list.emoji} {item_list.title}",
                callback_data=f"share:toggle:{item_list.id}",
            )
        ]
        for item_list in lists
    ]
    await message.answer(
        "Нажми на список, чтобы включить или выключить публичную ссылку.\n"
        "По такой ссылке гости увидят список и смогут забронировать подарок.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("share:toggle:"))
async def toggle_share(callback: CallbackQuery) -> None:
    list_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        item_list = await items_service.get_list(session, user.household_id, list_id)
        if item_list is None:
            await callback.answer("Список не найден", show_alert=True)
            return
        item_list.is_shared = not item_list.is_shared
        await session.commit()
        is_shared, token = item_list.is_shared, item_list.share_token
        title = f"{item_list.emoji} {item_list.title}"

    if is_shared:
        url = settings.share_url(token)
        await callback.message.answer(
            f"🔗 Ссылка на «{escape(title)}» готова, можно отправлять друзьям:\n{escape(url)}",
            reply_markup=kb.share_link_button(url),
            disable_web_page_preview=True,
        )
    else:
        await callback.message.answer(f"🔒 Список «{escape(title)}» снова закрыт.")
    await callback.answer()


@router.message(Command("stats"))
@router.message(F.text == "📊 За месяц")
async def stats(message: Message) -> None:
    today = dt.date.today()
    start = today.replace(day=1)
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        rows = await session.execute(
            select(ExpenseCategory.title, ExpenseCategory.emoji, Expense.currency,
                   func.sum(Expense.amount), func.count(Expense.id))
            .outerjoin(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
            .where(
                Expense.household_id == user.household_id,
                Expense.is_template.is_(False),
                Expense.spent_on >= start,
                Expense.spent_on <= today,
            )
            .group_by(ExpenseCategory.title, ExpenseCategory.emoji, Expense.currency)
            .order_by(func.sum(Expense.amount).desc())
        )
        rows = list(rows)

    if not rows:
        await message.answer("В этом месяце трат ещё нет 🙂\n\nПопробуй: <code>450 бензин</code>")
        return

    totals: dict[str, float] = {}
    lines = [f"<b>📊 {start.strftime('%m.%Y')}</b>", ""]
    for title, emoji, currency, total, count in rows:
        totals[currency] = totals.get(currency, 0) + float(total)
        lines.append(
            f"{emoji or '❔'} {escape(title or 'Без категории')} — "
            f"<b>{money(total, currency)}</b> ({count})"
        )
    lines.append("")
    for currency, total in totals.items():
        lines.append(f"Итого: <b>{money(total, currency)}</b>")
    await message.answer("\n".join(lines), reply_markup=kb.open_app_button("Подробнее"))


@router.message(Command("expenses"))
@router.message(F.text == "💸 Траты")
async def last_expenses(message: Message) -> None:
    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        rows = list(
            await session.scalars(
                select(Expense)
                .options(selectinload(Expense.category))
                .where(Expense.household_id == user.household_id, Expense.is_template.is_(False))
                .order_by(Expense.spent_on.desc(), Expense.id.desc())
                .limit(10)
            )
        )
    if not rows:
        await message.answer(SPEND_HELP)
        return
    lines = ["<b>💸 Последние траты</b>", ""]
    for expense in rows:
        emoji = expense.category.emoji if expense.category else "❔"
        lines.append(
            f"{expense.spent_on.strftime('%d.%m')} {emoji} "
            f"{escape(expense.title or (expense.category.title if expense.category else 'Трата'))} — "
            f"<b>{money(expense.amount, expense.currency)}</b>"
        )
    await message.answer("\n".join(lines), reply_markup=kb.open_app_button("Все траты"))


@router.message(F.text.func(lambda text: bool(extract_urls(text or ""))))
async def handle_link(message: Message) -> None:
    urls = extract_urls(message.text or "")
    note = (message.caption or "").strip() or None
    placeholder = await message.answer("Смотрю, что там за товар… ⏳")

    try:
        async with SessionLocal() as session:
            user = await resolve_user(session, message)
            for url in urls[:5]:
                item, item_list, confident = await items_service.add_item(
                    session, user, url=url, note=note
                )
                text = item_card(item, item_list)
                if not confident:
                    text += "\n\n<i>Категорию выбрала наугад — поправь, если что.</i>"
                await message.answer(
                    text,
                    reply_markup=kb.item_actions(item.id),
                    disable_web_page_preview=not item.image_url,
                )
    finally:
        await placeholder.delete()


@router.message(F.text.regexp(r"^\s*[-–—]?\s*\d"))
async def handle_expense(message: Message) -> None:
    parsed = parse_expense(message.text or "")
    if parsed is None:
        return

    async with SessionLocal() as session:
        user = await resolve_user(session, message)
        category = await session.scalar(
            select(ExpenseCategory).where(
                ExpenseCategory.household_id == user.household_id,
                ExpenseCategory.slug == parsed.category_slug,
            )
        )
        expense = Expense(
            household_id=user.household_id,
            category_id=category.id if category else None,
            title=parsed.title,
            amount=parsed.amount,
            currency=parsed.currency or settings.default_currency,
            period=parsed.period,
            spent_on=dt.date.today(),
            created_by_id=user.id,
        )
        session.add(expense)
        await session.commit()
        expense.category = category
        text = expense_card(expense)
        expense_id = expense.id

    await message.answer(text, reply_markup=kb.expense_actions(expense_id))


@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer(
        "Не поняла 🤔 Пришли ссылку на товар или сумму траты — например, "
        "<code>450 бензин</code>.\n\nВсё остальное удобнее в приложении:",
        reply_markup=kb.open_app_button(),
    )


# --- Кнопки под карточкой товара -------------------------------------------------


async def _load_item_for(session: AsyncSession, user: User, item_id: int) -> Item | None:
    return await session.scalar(
        select(Item)
        .options(selectinload(Item.list))
        .join(ItemList)
        .where(Item.id == item_id, ItemList.household_id == user.household_id)
    )


@router.callback_query(F.data.startswith("item:pick:"))
async def pick_category(callback: CallbackQuery) -> None:
    item_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        lists = list(
            await session.scalars(
                select(ItemList)
                .where(ItemList.household_id == user.household_id)
                .order_by(ItemList.kind, ItemList.position, ItemList.id)
            )
        )
    await callback.message.edit_reply_markup(reply_markup=kb.list_picker(item_id, lists))
    await callback.answer()


@router.callback_query(F.data.startswith("item:back:"))
async def back_to_item(callback: CallbackQuery) -> None:
    item_id = int(callback.data.split(":")[2])
    await callback.message.edit_reply_markup(reply_markup=kb.item_actions(item_id))
    await callback.answer()


@router.callback_query(F.data.startswith("item:move:"))
async def move_item(callback: CallbackQuery) -> None:
    _, _, raw_item, raw_list = callback.data.split(":")
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        item = await _load_item_for(session, user, int(raw_item))
        target = await items_service.get_list(session, user.household_id, int(raw_list))
        if item is None or target is None:
            await callback.answer("Не нашла товар", show_alert=True)
            return
        item.list_id = target.id
        await session.commit()
        text = item_card(item, target)
    await callback.message.edit_text(
        text, reply_markup=kb.item_actions(item.id), disable_web_page_preview=True
    )
    await callback.answer("Переложила ✅")


@router.callback_query(F.data.startswith("item:buy:"))
async def mark_bought(callback: CallbackQuery) -> None:
    item_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        item = await _load_item_for(session, user, item_id)
        if item is None:
            await callback.answer("Не нашла товар", show_alert=True)
            return
        item.status = "bought"
        item.bought_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отметила как купленное ✅")


@router.callback_query(F.data.startswith("item:del:"))
async def delete_item(callback: CallbackQuery) -> None:
    item_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        item = await _load_item_for(session, user, item_id)
        if item is not None:
            await session.delete(item)
            await session.commit()
    await callback.message.edit_text("🗑 Удалила")
    await callback.answer()


# --- Кнопки под карточкой траты --------------------------------------------------


async def _load_expense_for(session: AsyncSession, user: User, expense_id: int) -> Expense | None:
    return await session.scalar(
        select(Expense)
        .options(selectinload(Expense.category))
        .where(Expense.id == expense_id, Expense.household_id == user.household_id)
    )


@router.callback_query(F.data.startswith("exp:pick:"))
async def pick_expense_category(callback: CallbackQuery) -> None:
    expense_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        categories = list(
            await session.scalars(
                select(ExpenseCategory)
                .where(ExpenseCategory.household_id == user.household_id)
                .order_by(ExpenseCategory.position, ExpenseCategory.id)
            )
        )
    await callback.message.edit_reply_markup(
        reply_markup=kb.expense_category_picker(expense_id, categories)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("exp:back:"))
async def back_to_expense(callback: CallbackQuery) -> None:
    expense_id = int(callback.data.split(":")[2])
    await callback.message.edit_reply_markup(reply_markup=kb.expense_actions(expense_id))
    await callback.answer()


@router.callback_query(F.data.startswith("exp:period:"))
async def choose_period(callback: CallbackQuery) -> None:
    expense_id = int(callback.data.split(":")[2])
    await callback.message.edit_reply_markup(reply_markup=kb.period_picker(expense_id))
    await callback.answer()


@router.callback_query(F.data.startswith("exp:set:"))
async def set_expense_category(callback: CallbackQuery) -> None:
    _, _, raw_expense, raw_category = callback.data.split(":")
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        expense = await _load_expense_for(session, user, int(raw_expense))
        category = await session.scalar(
            select(ExpenseCategory).where(
                ExpenseCategory.id == int(raw_category),
                ExpenseCategory.household_id == user.household_id,
            )
        )
        if expense is None or category is None:
            await callback.answer("Не нашла трату", show_alert=True)
            return
        expense.category_id = category.id
        await session.commit()
        expense.category = category
        text = expense_card(expense)
    await callback.message.edit_text(text, reply_markup=kb.expense_actions(int(raw_expense)))
    await callback.answer("Обновила ✅")


@router.callback_query(F.data.startswith("exp:setperiod:"))
async def set_expense_period(callback: CallbackQuery) -> None:
    _, _, raw_expense, period = callback.data.split(":")
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        expense = await _load_expense_for(session, user, int(raw_expense))
        if expense is None:
            await callback.answer("Не нашла трату", show_alert=True)
            return
        expense.period = period
        await session.commit()
        text = expense_card(expense)
    await callback.message.edit_text(text, reply_markup=kb.expense_actions(int(raw_expense)))
    await callback.answer(PERIODS.get(period, "Готово"))


@router.callback_query(F.data.startswith("exp:del:"))
async def delete_expense(callback: CallbackQuery) -> None:
    expense_id = int(callback.data.split(":")[2])
    async with SessionLocal() as session:
        user = await resolve_user(session, callback)
        expense = await _load_expense_for(session, user, expense_id)
        if expense is not None:
            await session.delete(expense)
            await session.commit()
    await callback.message.edit_text("🗑 Удалила трату")
    await callback.answer()
