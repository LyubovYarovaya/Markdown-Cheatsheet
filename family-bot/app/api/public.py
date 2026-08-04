"""Публичные страницы списков: гость открывает ссылку и бронирует подарок."""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..models import Household, Item, ItemList
from ..schemas import PublicListOut, ReserveIn, ReserveOut, UnreserveIn
from .serializers import public_item_out

router = APIRouter(prefix="/api/public")


async def _shared_list(session: AsyncSession, token: str) -> ItemList:
    item_list = await session.scalar(
        select(ItemList)
        .options(selectinload(ItemList.owner))
        .where(ItemList.share_token == token, ItemList.is_shared.is_(True))
    )
    if item_list is None:
        raise HTTPException(status_code=404, detail="Ссылка недействительна")
    return item_list


async def _shared_item(session: AsyncSession, token: str, item_id: int) -> Item:
    item_list = await _shared_list(session, token)
    item = await session.scalar(
        select(Item).where(Item.id == item_id, Item.list_id == item_list.id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    return item


@router.get("/{token}", response_model=PublicListOut)
async def public_list(
    token: str,
    secret: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> PublicListOut:
    item_list = await _shared_list(session, token)
    household = await session.get(Household, item_list.household_id)
    items = list(
        await session.scalars(
            select(Item)
            .where(Item.list_id == item_list.id, Item.status == "active")
            .order_by(Item.priority.desc(), Item.id.desc())
        )
    )
    return PublicListOut(
        title=item_list.title,
        emoji=item_list.emoji,
        kind=item_list.kind,
        owner_name=item_list.owner.display_name if item_list.owner else None,
        household_title=household.title if household else "",
        hide_from_owner=item_list.hide_reservations_from_owner,
        items=[public_item_out(item, secret, hide_reservation=False) for item in items],
    )


@router.post("/{token}/items/{item_id}/reserve", response_model=ReserveOut)
async def reserve(
    token: str,
    item_id: int,
    payload: ReserveIn,
    session: AsyncSession = Depends(get_session),
) -> ReserveOut:
    item = await _shared_item(session, token, item_id)
    secret = payload.secret or secrets.token_urlsafe(16)

    if item.reserved_by and item.reserved_secret != secret:
        raise HTTPException(status_code=409, detail="Этот подарок уже забронировали")

    item.reserved_by = payload.name.strip()[:120]
    item.reserved_secret = secret
    item.reserved_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    return ReserveOut(ok=True, secret=secret)


@router.post("/{token}/items/{item_id}/unreserve", response_model=ReserveOut)
async def unreserve(
    token: str,
    item_id: int,
    payload: UnreserveIn,
    session: AsyncSession = Depends(get_session),
) -> ReserveOut:
    item = await _shared_item(session, token, item_id)
    if item.reserved_secret and item.reserved_secret != payload.secret:
        raise HTTPException(status_code=403, detail="Бронь оформил другой человек")
    item.reserved_by = item.reserved_secret = item.reserved_at = None
    await session.commit()
    return ReserveOut(ok=True, secret=payload.secret)
