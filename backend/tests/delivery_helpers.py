from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from app.delivery.contracts import PaymentSnapshot

# A test implementation of the participant-2 boundary, backed by real PostgreSQL.
# These are explicitly not production payment models or a guessed migration 0003.
metadata = MetaData()
rules = Table(
    "delivery_test_rules",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("title", String, nullable=False),
    Column("due_date", Date, nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("ensure_calls", Integer, nullable=False, default=0),
)
periods = Table(
    "delivery_test_periods",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("payment_id", Uuid, ForeignKey("delivery_test_rules.id"), nullable=False),
    Column("due_date", Date, nullable=False),
    Column("is_paid", Boolean, nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
    Column("currency", String, nullable=False),
    UniqueConstraint("payment_id", "due_date"),
)


class TestPaymentSource:
    __test__ = False

    async def active_payment_ids(self, db, *, after, limit):
        query = select(rules.c.id).where(rules.c.is_active.is_(True))
        if after:
            query = query.where(rules.c.id > after)
        return (await db.scalars(query.order_by(rules.c.id).limit(limit))).all()

    async def lock_rule(self, db, payment_id):
        return (
            await db.scalar(
                select(rules.c.is_active).where(rules.c.id == payment_id).with_for_update()
            )
            is True
        )

    async def ensure_payment_periods(self, db, payment_id, today, through=None):
        assert isinstance(today, date)
        assert db.in_transaction()
        row = (await db.execute(select(rules).where(rules.c.id == payment_id))).mappings().one()
        await db.execute(
            update(rules)
            .where(rules.c.id == payment_id)
            .values(ensure_calls=rules.c.ensure_calls + 1)
        )
        await db.execute(
            insert(periods)
            .values(
                id=uuid4(),
                payment_id=payment_id,
                due_date=row["due_date"],
                is_paid=False,
                amount=Decimal("123.45"),
                currency="RUB",
            )
            .on_conflict_do_nothing(index_elements=[periods.c.payment_id, periods.c.due_date])
        )

    async def unpaid_occurrences(self, db, payment_id):
        ids = (
            await db.scalars(
                select(periods.c.id).where(
                    periods.c.payment_id == payment_id, periods.c.is_paid.is_(False)
                )
            )
        ).all()
        return [await self.occurrence(db, payment_id, occurrence_id) for occurrence_id in ids]

    async def occurrence(self, db, payment_id, occurrence_id):
        row = (
            (
                await db.execute(
                    select(periods, rules.c.title, rules.c.is_active)
                    .join(rules, rules.c.id == periods.c.payment_id)
                    .where(periods.c.payment_id == payment_id, periods.c.id == occurrence_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return PaymentSnapshot(
            payment_id,
            occurrence_id,
            row["due_date"],
            row["title"],
            row["amount"],
            row["currency"],
            row["is_active"],
            row["is_paid"],
        )


async def add_payment(
    database,
    *,
    due_date=date(2026, 11, 10),
    active=True,
    paid=False,
    payment_id: UUID | None = None,
    create_period=True,
):
    payment_id, occurrence_id = payment_id or uuid4(), uuid4()
    async with database.session_factory() as db, db.begin():
        await db.execute(
            insert(rules).values(
                id=payment_id,
                title="Office <rent>",
                due_date=due_date,
                is_active=active,
                ensure_calls=0,
            )
        )
        if create_period:
            await db.execute(
                insert(periods).values(
                    id=occurrence_id,
                    payment_id=payment_id,
                    due_date=due_date,
                    is_paid=paid,
                    amount=Decimal("123.45"),
                    currency="RUB",
                )
            )
    return payment_id, occurrence_id
