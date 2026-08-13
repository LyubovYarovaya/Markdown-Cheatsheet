"""Пары ключ-значение, которые должны пережить перезапуск."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AppState


async def get_state(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AppState, key)
    return row.value if row else None


async def set_state(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppState, key)
    if row is None:
        session.add(AppState(key=key, value=value))
    else:
        row.value = value
    await session.commit()
