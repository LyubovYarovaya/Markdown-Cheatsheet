"""Добавление товаров — общая логика для бота и API."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Item, ItemList, User
from . import categorizer
from .link_parser import LinkPreview, canonical_url, fetch_preview, shop_name


@dataclass(slots=True)
class AddResult:
    item: Item
    list: ItemList
    confident: bool
    duplicate: bool = False


async def get_list(session: AsyncSession, household_id: int, list_id: int) -> ItemList | None:
    return await session.scalar(
        select(ItemList).where(ItemList.id == list_id, ItemList.household_id == household_id)
    )


async def list_by_slug(
    session: AsyncSession, household_id: int, slug: str, kind: str = "shopping"
) -> ItemList | None:
    return await session.scalar(
        select(ItemList).where(
            ItemList.household_id == household_id,
            ItemList.kind == kind,
            ItemList.slug == slug,
        )
    )


async def fallback_list(session: AsyncSession, household_id: int) -> ItemList:
    """Куда класть товар, если категорию определить не удалось."""
    target = await list_by_slug(session, household_id, "other")
    if target is not None:
        return target
    target = await session.scalar(
        select(ItemList)
        .where(ItemList.household_id == household_id, ItemList.kind == "shopping")
        .order_by(ItemList.position)
        .limit(1)
    )
    if target is None:  # у семьи снесли все категории покупок — создаём заново
        target = ItemList(
            household_id=household_id, kind="shopping", slug="other",
            title="Разное", emoji="📦", position=99,
        )
        session.add(target)
        await session.flush()
    return target


async def pick_list_for(
    session: AsyncSession, household_id: int, preview: LinkPreview
) -> tuple[ItemList, bool]:
    """Подбирает категорию под товар. Второй элемент — уверен ли алгоритм."""
    guess = categorizer.guess_category(title=preview.title, url=preview.url)
    if guess.slug != "other":
        target = await list_by_slug(session, household_id, guess.slug)
        if target is not None:
            return target, guess.confident
    return await fallback_list(session, household_id), False


async def find_by_url(session: AsyncSession, household_id: int, url: str) -> Item | None:
    """Ищет уже сохранённый товар с такой же ссылкой в пределах семьи."""
    if not url:
        return None
    key = canonical_url(url)
    if not key:
        return None

    rows = await session.scalars(
        select(Item)
        .options(selectinload(Item.created_by), selectinload(Item.list))
        .join(ItemList)
        .where(ItemList.household_id == household_id, Item.url.is_not(None))
    )
    for row in rows:
        if canonical_url(row.url) == key:
            return row
    return None


async def add_item(
    session: AsyncSession,
    user: User,
    *,
    url: str | None = None,
    title: str | None = None,
    list_id: int | None = None,
    price=None,
    currency: str | None = None,
    note: str | None = None,
    priority: int = 0,
    allow_duplicate: bool = False,
) -> AddResult:
    """Создаёт товар. Если передана ссылка — подтягивает данные со страницы.

    Если такая ссылка уже сохранена в семье, второй раз не добавляет:
    возвращает найденный товар с пометкой duplicate.
    """
    preview = LinkPreview(url=url or "", title=title)
    if url:
        # Сначала дешёвая проверка по самой ссылке — часто дубль виден сразу.
        if not allow_duplicate:
            existing = await find_by_url(session, user.household_id, url)
            if existing is not None:
                return AddResult(existing, existing.list, True, duplicate=True)

        preview = await fetch_preview(url)
        if title:
            preview.title = title

        # После редиректов ссылка могла превратиться в уже известную.
        if not allow_duplicate and preview.url and preview.url != url:
            existing = await find_by_url(session, user.household_id, preview.url)
            if existing is not None:
                return AddResult(existing, existing.list, True, duplicate=True)

    confident = True
    target: ItemList | None = None
    if list_id is not None:
        target = await get_list(session, user.household_id, list_id)
    if target is None:
        if url:
            target, confident = await pick_list_for(session, user.household_id, preview)
        else:
            guess = categorizer.guess_category(title=title)
            target = (
                await list_by_slug(session, user.household_id, guess.slug)
                if guess.slug != "other"
                else None
            ) or await fallback_list(session, user.household_id)
            confident = guess.confident

    item = Item(
        list_id=target.id,
        title=(preview.title or title or (shop_name(url) if url else "Без названия"))[:300],
        url=preview.url or url,
        image_url=preview.image_url,
        shop=preview.shop,
        price=price if price is not None else preview.price,
        currency=currency or preview.currency,
        note=note,
        priority=priority,
        created_by_id=user.id,
    )
    session.add(item)
    await session.commit()

    item = await session.scalar(
        select(Item).options(selectinload(Item.created_by)).where(Item.id == item.id)
    )
    return AddResult(item, target, confident, duplicate=False)
