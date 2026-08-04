import os
import pathlib
import sys

# Тестовое окружение задаём до импорта приложения — настройки читаются один раз.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:TEST-TOKEN")
os.environ.setdefault("BOT_MODE", "off")
os.environ.setdefault("DEV_TG_ID", "777")
os.environ.setdefault("PUBLIC_URL", "https://test.local")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{ROOT / 'tests' / 'test.db'}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_db():
    path = ROOT / "tests" / "test.db"
    path.unlink(missing_ok=True)
    yield
    path.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client():
    from app.db import init_db
    from app.main import app

    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
