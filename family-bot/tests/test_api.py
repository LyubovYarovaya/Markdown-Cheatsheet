import datetime as dt

import pytest

pytestmark = pytest.mark.asyncio


async def test_bootstrap_creates_default_lists(client):
    me = (await client.get("/api/me")).json()
    assert me["household_id"]

    lists = (await client.get("/api/lists")).json()
    shopping = {row["slug"] for row in lists if row["kind"] == "shopping"}
    assert {"tech", "kitchen", "home", "textile", "baby"} <= shopping

    wishlists = [row for row in lists if row["kind"] == "wishlist"]
    assert any(row["owner_id"] is None for row in wishlists)  # общий
    assert any(row["owner_id"] is not None for row in wishlists)  # личный

    categories = (await client.get("/api/expense-categories")).json()
    assert {"car", "health"} <= {row["slug"] for row in categories}


async def test_item_lands_in_guessed_category(client):
    created = (await client.post("/api/items", json={"title": "Автокресло Cybex"})).json()
    lists = (await client.get("/api/lists")).json()
    baby = next(row for row in lists if row["slug"] == "baby")
    assert created["list_id"] == baby["id"]

    items = (await client.get(f"/api/lists/{baby['id']}/items")).json()
    assert any(row["id"] == created["id"] for row in items)

    updated = (await client.patch(f"/api/items/{created['id']}", json={"status": "bought"})).json()
    assert updated["status"] == "bought"

    assert (await client.delete(f"/api/items/{created['id']}")).json() == {"ok": True}


async def test_expenses_and_summary(client):
    categories = (await client.get("/api/expense-categories")).json()
    car = next(row for row in categories if row["slug"] == "car")
    today = dt.date.today().isoformat()

    await client.post("/api/expenses", json={
        "amount": 450, "title": "бензин", "category_id": car["id"], "spent_on": today,
    })
    await client.post("/api/expenses", json={
        "amount": 1000, "title": "аренда", "period": "monthly", "is_template": True,
    })

    summary = (await client.get(f"/api/expenses/summary?date_from={today}&date_to={today}")).json()
    assert summary["total"] == 450
    assert summary["planned_monthly"] == 1000
    assert summary["by_category"][0]["title"] == "Машина"

    templates = (await client.get("/api/expenses?templates=true")).json()
    assert len(templates) == 1

    paid = (await client.post(f"/api/expenses/{templates[0]['id']}/pay", json={})).json()
    assert paid["amount"] == 1000 and paid["is_template"] is False


async def test_share_and_reserve_flow(client):
    lists = (await client.get("/api/lists")).json()
    baby = next(row for row in lists if row["slug"] == "baby")
    item = (await client.post("/api/items", json={"title": "Пеленальный столик", "list_id": baby["id"]})).json()

    shared = (await client.patch(f"/api/lists/{baby['id']}", json={"is_shared": True})).json()
    token = shared["share_url"].rsplit("/", 1)[-1]

    public = (await client.get(f"/api/public/{token}")).json()
    assert public["title"] == "Baby"
    assert any(row["id"] == item["id"] for row in public["items"])

    reserved = (await client.post(
        f"/api/public/{token}/items/{item['id']}/reserve",
        json={"name": "Оля", "secret": "guest-1"},
    )).json()
    assert reserved["ok"]

    conflict = await client.post(
        f"/api/public/{token}/items/{item['id']}/reserve",
        json={"name": "Ира", "secret": "guest-2"},
    )
    assert conflict.status_code == 409

    mine = (await client.get(f"/api/public/{token}?secret=guest-1")).json()
    booked = next(row for row in mine["items"] if row["id"] == item["id"])
    assert booked["is_reserved"] and booked["mine"] and booked["reserved_by"] == "Оля"

    released = await client.post(
        f"/api/public/{token}/items/{item['id']}/unreserve", json={"secret": "guest-1"}
    )
    assert released.json()["ok"]

    await client.patch(f"/api/lists/{baby['id']}", json={"is_shared": False})
    assert (await client.get(f"/api/public/{token}")).status_code == 404


async def test_personal_wishlist_hides_reservations_from_owner(client):
    lists = (await client.get("/api/lists")).json()
    personal = next(row for row in lists if row["kind"] == "wishlist" and row["owner_id"])
    item = (await client.post("/api/items", json={"title": "Книга", "list_id": personal["id"]})).json()

    shared = (await client.patch(f"/api/lists/{personal['id']}", json={"is_shared": True})).json()
    token = shared["share_url"].rsplit("/", 1)[-1]
    await client.post(
        f"/api/public/{token}/items/{item['id']}/reserve", json={"name": "Аня", "secret": "g"}
    )

    # Гость бронь видит...
    public = (await client.get(f"/api/public/{token}")).json()
    assert public["items"][0]["is_reserved"] is True
    # ...а владелец вишлиста — нет.
    owner_view = (await client.get(f"/api/lists/{personal['id']}/items")).json()
    assert owner_view[0]["is_reserved"] is False
    assert owner_view[0]["reserved_by"] is None


async def test_auth_required_without_dev_id(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dev_tg_id", None)
    assert (await client.get("/api/me")).status_code == 401
