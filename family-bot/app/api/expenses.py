from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import current_user
from ..config import settings
from ..db import get_session
from ..models import PERIODS, Expense, ExpenseCategory, User
from ..schemas import (
    ExpenseCategoryCreate,
    ExpenseCategoryOut,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    SummaryBucket,
    SummaryOut,
)
from .serializers import expense_out

router = APIRouter(prefix="/api")


def month_bounds(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or dt.date.today()
    start = today.replace(day=1)
    next_month = (start + dt.timedelta(days=32)).replace(day=1)
    return start, next_month - dt.timedelta(days=1)


async def _load_expense(session: AsyncSession, user: User, expense_id: int) -> Expense:
    expense = await session.scalar(
        select(Expense)
        .options(selectinload(Expense.category), selectinload(Expense.created_by))
        .where(Expense.id == expense_id, Expense.household_id == user.household_id)
    )
    if expense is None:
        raise HTTPException(status_code=404, detail="Трата не найдена")
    return expense


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
async def get_expense_categories(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ExpenseCategoryOut]:
    rows = await session.scalars(
        select(ExpenseCategory)
        .where(ExpenseCategory.household_id == user.household_id)
        .order_by(ExpenseCategory.position, ExpenseCategory.id)
    )
    return [
        ExpenseCategoryOut(
            id=row.id, slug=row.slug, title=row.title, emoji=row.emoji, position=row.position
        )
        for row in rows
    ]


@router.post("/expense-categories", response_model=ExpenseCategoryOut)
async def create_expense_category(
    payload: ExpenseCategoryCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ExpenseCategoryOut:
    title = payload.title.strip()[:120]
    if not title:
        raise HTTPException(status_code=400, detail="Пустое название")
    position = await session.scalar(
        select(func.max(ExpenseCategory.position)).where(
            ExpenseCategory.household_id == user.household_id
        )
    )
    category = ExpenseCategory(
        household_id=user.household_id,
        slug=f"custom{int(dt.datetime.now().timestamp())}",
        title=title,
        emoji=payload.emoji or "💸",
        position=(position or 0) + 1,
    )
    session.add(category)
    await session.commit()
    return ExpenseCategoryOut(
        id=category.id, slug=category.slug, title=category.title,
        emoji=category.emoji, position=category.position,
    )


@router.delete("/expense-categories/{category_id}")
async def delete_expense_category(
    category_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    category = await session.scalar(
        select(ExpenseCategory).where(
            ExpenseCategory.id == category_id,
            ExpenseCategory.household_id == user.household_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    # Траты не удаляем — просто отвязываем, иначе они потеряются из истории.
    await session.execute(
        update(Expense).where(Expense.category_id == category.id).values(category_id=None)
    )
    await session.delete(category)
    await session.commit()
    return {"ok": True}


@router.get("/expenses", response_model=list[ExpenseOut])
async def get_expenses(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    period: str | None = None,
    category_id: int | None = None,
    templates: bool = Query(default=False, description="только шаблоны регулярных трат"),
    limit: int = Query(default=300, le=1000),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ExpenseOut]:
    query = (
        select(Expense)
        .options(selectinload(Expense.category), selectinload(Expense.created_by))
        .where(Expense.household_id == user.household_id, Expense.is_template.is_(templates))
        .order_by(Expense.spent_on.desc(), Expense.id.desc())
        .limit(limit)
    )
    if not templates:
        if date_from is None or date_to is None:
            date_from, date_to = month_bounds()
        query = query.where(Expense.spent_on >= date_from, Expense.spent_on <= date_to)
    if period:
        query = query.where(Expense.period == period)
    if category_id:
        query = query.where(Expense.category_id == category_id)

    return [expense_out(row) for row in await session.scalars(query)]


@router.post("/expenses", response_model=ExpenseOut)
async def create_expense(
    payload: ExpenseCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ExpenseOut:
    if payload.amount is None or Decimal(payload.amount) <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")
    if payload.category_id is not None:
        exists = await session.scalar(
            select(ExpenseCategory.id).where(
                ExpenseCategory.id == payload.category_id,
                ExpenseCategory.household_id == user.household_id,
            )
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="Категория не найдена")

    expense = Expense(
        household_id=user.household_id,
        category_id=payload.category_id,
        title=(payload.title or "").strip()[:200],
        amount=payload.amount,
        currency=(payload.currency or settings.default_currency).upper()[:8],
        period=payload.period,
        spent_on=payload.spent_on or dt.date.today(),
        note=payload.note,
        is_template=payload.is_template,
        created_by_id=user.id,
    )
    session.add(expense)
    await session.commit()
    return expense_out(await _load_expense(session, user, expense.id))


@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ExpenseOut:
    expense = await _load_expense(session, user, expense_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)
    await session.commit()
    return expense_out(await _load_expense(session, user, expense_id))


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    expense = await _load_expense(session, user, expense_id)
    await session.delete(expense)
    await session.commit()
    return {"ok": True}


@router.post("/expenses/{expense_id}/pay", response_model=ExpenseOut)
async def pay_template(
    expense_id: int,
    payload: dict | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ExpenseOut:
    """Отметить регулярную трату оплаченной — создаёт факт по шаблону."""
    template = await _load_expense(session, user, expense_id)
    if not template.is_template:
        raise HTTPException(status_code=400, detail="Это не шаблон регулярной траты")

    payload = payload or {}
    amount = payload.get("amount")
    fact = Expense(
        household_id=template.household_id,
        category_id=template.category_id,
        title=template.title,
        amount=Decimal(str(amount)) if amount is not None else template.amount,
        currency=template.currency,
        period=template.period,
        spent_on=dt.date.today(),
        note=template.note,
        is_template=False,
        created_by_id=user.id,
    )
    session.add(fact)
    await session.commit()
    return expense_out(await _load_expense(session, user, fact.id))


@router.get("/expenses/summary", response_model=SummaryOut)
async def summary(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    currency: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SummaryOut:
    if date_from is None or date_to is None:
        date_from, date_to = month_bounds()
    currency = (currency or settings.default_currency).upper()

    base = (
        select(Expense)
        .where(
            Expense.household_id == user.household_id,
            Expense.is_template.is_(False),
            Expense.spent_on >= date_from,
            Expense.spent_on <= date_to,
        )
        .options(selectinload(Expense.category))
    )
    rows = list(await session.scalars(base))

    by_currency: dict[str, list[float | int]] = {}
    by_category: dict[int | None, list] = {}
    by_period: dict[str, list[float | int]] = {}
    by_month: dict[str, list[float | int]] = {}
    total = 0.0

    for row in rows:
        amount = float(row.amount)
        bucket = by_currency.setdefault(row.currency, [0.0, 0])
        bucket[0] += amount
        bucket[1] += 1
        if row.currency != currency:
            continue

        total += amount
        category = by_category.setdefault(
            row.category_id,
            [row.category.title if row.category else "Без категории",
             row.category.emoji if row.category else "❔", 0.0, 0],
        )
        category[2] += amount
        category[3] += 1

        period = by_period.setdefault(row.period, [0.0, 0])
        period[0] += amount
        period[1] += 1

        key = row.spent_on.strftime("%Y-%m")
        month = by_month.setdefault(key, [0.0, 0])
        month[0] += amount
        month[1] += 1

    templates = list(
        await session.scalars(
            select(Expense).where(
                Expense.household_id == user.household_id,
                Expense.is_template.is_(True),
                Expense.currency == currency,
            )
        )
    )
    planned = {"monthly": 0.0, "quarterly": 0.0, "yearly": 0.0}
    for template in templates:
        if template.period in planned:
            planned[template.period] += float(template.amount)

    return SummaryOut(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        total=round(total, 2),
        by_category=sorted(
            [
                SummaryBucket(
                    key=str(cid), title=data[0], emoji=data[1],
                    total=round(data[2], 2), count=data[3],
                )
                for cid, data in by_category.items()
            ],
            key=lambda b: b.total,
            reverse=True,
        ),
        by_period=[
            SummaryBucket(
                key=key, title=PERIODS.get(key, key),
                total=round(value[0], 2), count=value[1],
            )
            for key, value in sorted(by_period.items())
        ],
        by_month=[
            SummaryBucket(key=key, title=key, total=round(value[0], 2), count=value[1])
            for key, value in sorted(by_month.items())
        ],
        by_currency=[
            SummaryBucket(key=key, title=key, total=round(value[0], 2), count=value[1])
            for key, value in sorted(by_currency.items())
        ],
        planned_monthly=round(planned["monthly"], 2),
        planned_quarterly=round(planned["quarterly"], 2),
        planned_yearly=round(planned["yearly"], 2),
    )
