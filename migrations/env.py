import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from voice_ingest.runtime.database import Base

connection = context.config.attributes.get("connection")
url = os.environ.get("VOICE_DATABASE_URL")
if not url and connection is None:
    from dotenv import load_dotenv

    load_dotenv()
    url = os.environ["VOICE_DATABASE_URL"]


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if connection is not None:
    migrate(connection)
elif context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
