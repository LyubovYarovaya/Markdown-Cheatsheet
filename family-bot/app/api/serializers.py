from __future__ import annotations

from ..config import settings
from ..models import Expense, Item, ItemList, User
from ..schemas import ExpenseOut, ItemOut, ListOut, PublicItemOut, UserOut


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, tg_id=user.tg_id, name=user.display_name)


def list_out(
    item_list: ItemList,
    owner_name: str | None = None,
    active_count: int = 0,
    bought_count: int = 0,
    total_price: float | None = None,
) -> ListOut:
    return ListOut(
        id=item_list.id,
        kind=item_list.kind,
        slug=item_list.slug,
        title=item_list.title,
        emoji=item_list.emoji,
        owner_id=item_list.owner_id,
        owner_name=owner_name,
        position=item_list.position,
        is_shared=item_list.is_shared,
        share_url=settings.share_url(item_list.share_token) if item_list.is_shared else None,
        active_count=active_count,
        bought_count=bought_count,
        total_price=total_price,
    )


def item_out(item: Item, viewer: User | None = None, hide_reservation: bool = False) -> ItemOut:
    reserved = bool(item.reserved_by)
    return ItemOut(
        id=item.id,
        list_id=item.list_id,
        title=item.title,
        url=item.url,
        image_url=item.image_url,
        shop=item.shop,
        price=float(item.price) if item.price is not None else None,
        currency=item.currency,
        note=item.note,
        priority=item.priority,
        status=item.status,
        created_by=item.created_by.display_name if item.created_by else None,
        created_at=item.created_at,
        reserved_by=None if hide_reservation else item.reserved_by,
        is_reserved=False if hide_reservation else reserved,
    )


def public_item_out(item: Item, secret: str | None, hide_reservation: bool) -> PublicItemOut:
    reserved = bool(item.reserved_by)
    return PublicItemOut(
        id=item.id,
        title=item.title,
        url=item.url,
        image_url=item.image_url,
        price=float(item.price) if item.price is not None else None,
        currency=item.currency,
        note=item.note,
        priority=item.priority,
        status=item.status,
        reserved_by=None if hide_reservation else item.reserved_by,
        is_reserved=False if hide_reservation else reserved,
        mine=bool(reserved and secret and item.reserved_secret == secret),
    )


def expense_out(expense: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        title=expense.title,
        amount=float(expense.amount),
        currency=expense.currency,
        period=expense.period,
        spent_on=expense.spent_on,
        note=expense.note,
        is_template=expense.is_template,
        category_id=expense.category_id,
        category_title=expense.category.title if expense.category else None,
        category_emoji=expense.category.emoji if expense.category else None,
        created_by=expense.created_by.display_name if expense.created_by else None,
    )
