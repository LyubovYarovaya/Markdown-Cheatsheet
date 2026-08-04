from __future__ import annotations

import datetime as dt
import secrets
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_token(n: int = 12) -> str:
    return secrets.token_urlsafe(n)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Household(Base, TimestampMixin):
    """Семья — общее пространство, в которое приглашаются участники."""

    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="Наша семья")
    invite_code: Mapped[str] = mapped_column(String(32), unique=True, default=new_token)

    members: Mapped[list[User]] = relationship(back_populates="household")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    household_id: Mapped[int | None] = mapped_column(
        ForeignKey("households.id", ondelete="SET NULL"), nullable=True
    )

    household: Mapped[Household | None] = relationship(back_populates="members")

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or f"id{self.tg_id}"


class ItemList(Base, TimestampMixin):
    """Список вещей: либо категория покупок, либо вишлист.

    kind='shopping' — техника, кухня, квартира, текстиль, baby, ...
    kind='wishlist' — общий вишлист семьи (owner_id=None) или личный (owner_id=user).
    """

    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="shopping")
    slug: Mapped[str] = mapped_column(String(48), default="")
    title: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(8), default="📦")
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=100)

    share_token: Mapped[str] = mapped_column(String(32), unique=True, default=new_token)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    # Для личного вишлиста прячем брони от владельца — чтобы подарок остался сюрпризом.
    hide_reservations_from_owner: Mapped[bool] = mapped_column(Boolean, default=False)

    owner: Mapped[User | None] = relationship()
    items: Mapped[list[Item]] = relationship(
        back_populates="list", cascade="all, delete-orphan"
    )


class Item(Base, TimestampMixin):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 0 обычный, 1 важный
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|bought
    bought_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Бронирование гостем по публичной ссылке.
    reserved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reserved_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    list: Mapped[ItemList] = relationship(back_populates="items")
    created_by: Mapped[User | None] = relationship()


class ExpenseCategory(Base, TimestampMixin):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("household_id", "slug", name="uq_expcat_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(8), default="💸")
    position: Mapped[int] = mapped_column(Integer, default=100)


class Expense(Base, TimestampMixin):
    """Трата.

    period описывает характер траты: разовая, ежемесячная, ежеквартальная, годовая.
    Регулярные траты заводятся один раз (is_template=True) и разворачиваются
    в конкретные записи по факту оплаты.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="UAH")
    period: Mapped[str] = mapped_column(String(16), default="once")
    spent_on: Mapped[dt.date] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[ExpenseCategory | None] = relationship()
    created_by: Mapped[User | None] = relationship()


PERIODS = {
    "once": "Разовая",
    "monthly": "Ежемесячная",
    "quarterly": "Ежеквартальная",
    "yearly": "Ежегодная",
}
