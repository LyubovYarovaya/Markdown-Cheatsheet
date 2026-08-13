import logging
from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

log = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(connection) -> None:
    """Догоняет схему при обновлении кода: добавляет новые nullable-колонки.

    Полноценных миграций тут нет — база семейная, схема простая. Но терять
    данные при обновлении нельзя, поэтому новые поля доливаем на месте.
    """
    inspector = inspect(connection)
    for table in Base.metadata.sorted_tables:
        if table.name not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or column.primary_key:
                continue
            if not column.nullable and column.default is None and column.server_default is None:
                log.warning(
                    "Колонка %s.%s не nullable — добавь её вручную", table.name, column.name
                )
                continue
            column_type = column.type.compile(connection.dialect)
            connection.execute(
                text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {column_type}')
            )
            log.info("Добавила колонку %s.%s", table.name, column.name)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
