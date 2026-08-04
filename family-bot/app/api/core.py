from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import runtime
from ..auth import current_user
from ..config import settings
from ..db import get_session
from ..models import Household, Item, ItemList, User, new_token
from ..schemas import (
    ItemCreate,
    ItemOut,
    LinkPreviewOut,
    ListCreate,
    ListOut,
    ListUpdate,
    ItemUpdate,
    MeOut,
)
from ..services import items as items_service
from ..services.defaults import ensure_personal_wishlist
from ..services.link_parser import fetch_preview
from ..services.users import household_members, join_household
from .serializers import item_out, list_out, user_out

router = APIRouter(prefix="/api")


async def _load_list(session: AsyncSession, user: User, list_id: int) -> ItemList:
    item_list = await items_service.get_list(session, user.household_id, list_id)
    if item_list is None:
        raise HTTPException(status_code=404, detail="Список не найден")
    return item_list


async def _load_item(session: AsyncSession, user: User, item_id: int) -> Item:
    item = await session.scalar(
        select(Item)
        .options(selectinload(Item.created_by), selectinload(Item.list))
        .join(ItemList)
        .where(Item.id == item_id, ItemList.household_id == user.household_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return item


@router.get("/me", response_model=MeOut)
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    household = await session.get(Household, user.household_id)
    members = await household_members(session, user.household_id)
    return MeOut(
        user=user_out(user),
        household_id=household.id,
        household_title=household.title,
        invite_code=household.invite_code,
        invite_url=runtime.invite_link(household.invite_code),
        members=[user_out(m) for m in members],
        currency=settings.default_currency,
    )


@router.post("/household/join")
async def household_join(
    payload: dict,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    code = (payload.get("code") or "").strip()
    household = await join_household(session, user, code)
    if household is None:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    return {"ok": True, "household_title": household.title}


@router.post("/household/reset-invite")
async def household_reset_invite(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    household = await session.get(Household, user.household_id)
    household.invite_code = new_token()
    await session.commit()
    return {"code": household.invite_code, "url": runtime.invite_link(household.invite_code)}


@router.get("/lists", response_model=list[ListOut])
async def get_lists(
    kind: str | None = Query(default=None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ListOut]:
    query = (
        select(ItemList)
        .options(selectinload(ItemList.owner))
        .where(ItemList.household_id == user.household_id)
        .order_by(ItemList.kind, ItemList.position, ItemList.id)
    )
    if kind:
        query = query.where(ItemList.kind == kind)
    lists = list(await session.scalars(query))

    stats_rows = await session.execute(
        select(
            Item.list_id,
            Item.status,
            func.count(Item.id),
            func.sum(Item.price),
        )
        .join(ItemList)
        .where(ItemList.household_id == user.household_id)
        .group_by(Item.list_id, Item.status)
    )
    stats: dict[int, dict[str, tuple[int, float]]] = {}
    for list_id, status, count, total in stats_rows:
        stats.setdefault(list_id, {})[status] = (count, float(total or 0))

    result = []
    for item_list in lists:
        by_status = stats.get(item_list.id, {})
        active_count, active_total = by_status.get("active", (0, 0.0))
        bought_count, _ = by_status.get("bought", (0, 0.0))
        result.append(
            list_out(
                item_list,
                owner_name=item_list.owner.display_name if item_list.owner else None,
                active_count=active_count,
                bought_count=bought_count,
                total_price=active_total or None,
            )
        )
    return result


@router.post("/lists", response_model=ListOut)
async def create_list(
    payload: ListCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ListOut:
    max_position = await session.scalar(
        select(func.max(ItemList.position)).where(
            ItemList.household_id == user.household_id, ItemList.kind == payload.kind
        )
    )
    item_list = ItemList(
        household_id=user.household_id,
        kind=payload.kind,
        slug=f"custom{int(dt.datetime.now().timestamp())}",
        title=payload.title.strip()[:120],
        emoji=payload.emoji or "📦",
        owner_id=user.id if (payload.kind == "wishlist" and payload.personal) else None,
        position=(max_position or 0) + 1,
        hide_reservations_from_owner=payload.kind == "wishlist" and payload.personal,
    )
    session.add(item_list)
    await session.commit()
    return list_out(item_list, owner_name=user.display_name if item_list.owner_id else None)


@router.patch("/lists/{list_id}", response_model=ListOut)
async def update_list(
    list_id: int,
    payload: ListUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ListOut:
    item_list = await _load_list(session, user, list_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item_list, field, value)
    await session.commit()
    owner = await session.get(User, item_list.owner_id) if item_list.owner_id else None
    return list_out(item_list, owner_name=owner.display_name if owner else None)


@router.delete("/lists/{list_id}")
async def delete_list(
    list_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item_list = await _load_list(session, user, list_id)
    await session.delete(item_list)
    await session.commit()
    return {"ok": True}


@router.get("/lists/{list_id}/items", response_model=list[ItemOut])
async def list_items(
    list_id: int,
    status: str = Query(default="all", pattern="^(all|active|bought)$"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ItemOut]:
    item_list = await _load_list(session, user, list_id)
    query = (
        select(Item)
        .options(selectinload(Item.created_by))
        .where(Item.list_id == item_list.id)
        .order_by(Item.status, Item.priority.desc(), Item.id.desc())
    )
    if status != "all":
        query = query.where(Item.status == status)
    rows = list(await session.scalars(query))

    # Владелец личного вишлиста не должен видеть, что уже забронировали.
    hide = item_list.hide_reservations_from_owner and item_list.owner_id == user.id
    return [item_out(row, viewer=user, hide_reservation=hide) for row in rows]


@router.post("/items", response_model=ItemOut)
async def create_item(
    payload: ItemCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ItemOut:
    if not payload.url and not payload.title:
        raise HTTPException(status_code=400, detail="Нужна ссылка или название")
    item, _, _ = await items_service.add_item(
        session,
        user,
        url=payload.url,
        title=payload.title,
        list_id=payload.list_id,
        price=payload.price,
        currency=payload.currency,
        note=payload.note,
        priority=payload.priority,
    )
    return item_out(item)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: int,
    payload: ItemUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ItemOut:
    item = await _load_item(session, user, item_id)
    data = payload.model_dump(exclude_unset=True)

    if "list_id" in data and data["list_id"] is not None:
        await _load_list(session, user, data["list_id"])  # проверяем доступ
    if data.get("status") == "bought" and item.status != "bought":
        item.bought_at = dt.datetime.now(dt.timezone.utc)
    if data.get("status") == "active":
        item.bought_at = None

    for field, value in data.items():
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return item_out(item)


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await _load_item(session, user, item_id)
    await session.delete(item)
    await session.commit()
    return {"ok": True}


@router.post("/items/{item_id}/unreserve")
async def clear_reservation(
    item_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Снять бронь вручную (например, гость передумал и написал в личку)."""
    item = await _load_item(session, user, item_id)
    item.reserved_by = item.reserved_secret = item.reserved_at = None
    await session.commit()
    return {"ok": True}


@router.post("/parse-link", response_model=LinkPreviewOut)
async def parse_link(
    payload: dict,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> LinkPreviewOut:
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Нужна ссылка")
    preview = await fetch_preview(url)
    target, _ = await items_service.pick_list_for(session, user.household_id, preview)
    return LinkPreviewOut(
        **preview.as_dict(),
        suggested_list_id=target.id,
        suggested_list_title=f"{target.emoji} {target.title}",
    )


@router.post("/wishlist/personal", response_model=ListOut)
async def personal_wishlist(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ListOut:
    wishlist = await ensure_personal_wishlist(session, user)
    await session.commit()
    return list_out(wishlist, owner_name=user.display_name)
