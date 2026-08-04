"""Пользователи и семьи — общая логика для бота и веб-приложения."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Household, ItemList, User
from .defaults import bootstrap_household, ensure_personal_wishlist


async def get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    first_name: str = "",
    username: str | None = None,
    language_code: str | None = None,
) -> User:
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        user = User(
            tg_id=tg_id,
            first_name=first_name,
            username=username,
            language_code=language_code,
        )
        session.add(user)
        await session.flush()
    else:
        # Имя в Telegram могло измениться.
        if first_name and user.first_name != first_name:
            user.first_name = first_name
        if username != user.username:
            user.username = username

    if user.household_id is None:
        household = Household(title="Наша семья")
        session.add(household)
        await session.flush()
        await bootstrap_household(session, household)
        user.household_id = household.id
        await session.flush()

    await ensure_personal_wishlist(session, user)
    await session.commit()
    await session.refresh(user)
    return user


async def join_household(session: AsyncSession, user: User, invite_code: str) -> Household | None:
    """Переводит пользователя в семью по коду приглашения."""
    household = await session.scalar(
        select(Household).where(Household.invite_code == invite_code)
    )
    if household is None or household.id == user.household_id:
        return household

    old_household_id = user.household_id
    user.household_id = household.id
    await session.flush()

    # Личный вишлист переезжает вместе с человеком.
    personal = await session.scalar(
        select(ItemList).where(
            ItemList.owner_id == user.id,
            ItemList.kind == "wishlist",
            ItemList.household_id == old_household_id,
        )
    )
    if personal is not None:
        personal.household_id = household.id
    else:
        await ensure_personal_wishlist(session, user)

    await session.commit()
    return household


async def household_members(session: AsyncSession, household_id: int) -> list[User]:
    result = await session.scalars(
        select(User).where(User.household_id == household_id).order_by(User.id)
    )
    return list(result)
