from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PAYMENTS_LOCK = (0x494E56, 2)


async def lock_payments(db: AsyncSession) -> None:
    """Global transaction lock, before rule/occurrence/outbox row locks; no commit."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
        {"namespace": PAYMENTS_LOCK[0], "resource": PAYMENTS_LOCK[1]},
    )
