"""Стартовое наполнение семьи: категории покупок, вишлисты, категории трат."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ExpenseCategory, Household, ItemList, User

DEFAULT_LISTS: list[tuple[str, str, str]] = [
    # slug, title, emoji
    ("tech", "Техника", "🔌"),
    ("kitchen", "Кухня", "🍳"),
    ("home", "Квартира", "🏠"),
    ("textile", "Текстиль", "🧵"),
    ("baby", "Baby", "🍼"),
    ("other", "Разное", "📦"),
]

DEFAULT_EXPENSE_CATEGORIES: list[tuple[str, str, str]] = [
    ("car", "Машина", "🚗"),
    ("health", "Здоровье", "🩺"),
    ("home", "Квартира", "🏠"),
    ("food", "Продукты", "🛒"),
    ("baby", "Baby", "🍼"),
    ("subscriptions", "Связь и подписки", "📱"),
    ("clothes", "Одежда", "👗"),
    ("fun", "Развлечения", "🎬"),
    ("other", "Другое", "💸"),
]


async def bootstrap_household(session: AsyncSession, household: Household) -> None:
    """Создаёт дефолтные категории и общий вишлист для новой семьи."""
    for pos, (slug, title, emoji) in enumerate(DEFAULT_LISTS):
        session.add(
            ItemList(
                household_id=household.id,
                kind="shopping",
                slug=slug,
                title=title,
                emoji=emoji,
                position=pos,
            )
        )
    for pos, (slug, title, emoji) in enumerate(DEFAULT_EXPENSE_CATEGORIES):
        session.add(
            ExpenseCategory(
                household_id=household.id,
                slug=slug,
                title=title,
                emoji=emoji,
                position=pos,
            )
        )
    session.add(
        ItemList(
            household_id=household.id,
            kind="wishlist",
            slug="common",
            title="Общий вишлист",
            emoji="🎁",
            owner_id=None,
            position=0,
        )
    )
    await session.flush()


async def ensure_personal_wishlist(session: AsyncSession, user: User) -> ItemList:
    """У каждого участника семьи есть свой вишлист."""
    existing = await session.scalar(
        select(ItemList).where(
            ItemList.household_id == user.household_id,
            ItemList.kind == "wishlist",
            ItemList.owner_id == user.id,
        )
    )
    if existing:
        return existing

    wishlist = ItemList(
        household_id=user.household_id,
        kind="wishlist",
        slug=f"user{user.id}",
        title=f"Вишлист: {user.display_name}",
        emoji="⭐",
        owner_id=user.id,
        position=10,
        hide_reservations_from_owner=True,
    )
    session.add(wishlist)
    await session.flush()
    return wishlist
