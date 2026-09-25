"""Real PostgreSQL locking test. Requires TEST_DATABASE_URL for an EMPTY test DB."""

import os
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base, User, Transfer, make_engine
from app.business import transfer_money


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Dedicated PostgreSQL test database unavailable",
)
def test_parallel_duplicate_and_opposite_transfers():
    engine = make_engine(os.environ["TEST_DATABASE_URL"])
    # Dedicated test schema: never drops application tables.
    import uuid

    schema = "test_" + uuid.uuid4().hex
    with engine.begin() as c:
        c.exec_driver_sql(f"CREATE SCHEMA {schema}")
    scoped = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(scoped)
    factory = sessionmaker(scoped, expire_on_commit=False)
    try:
        with factory.begin() as db:
            db.add_all(
                [
                    User(id=1, username="alice", password_hash="x", balance=10000),
                    User(id=2, username="bob", password_hash="x", balance=10000),
                ]
            )
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: transfer_money(
                        factory, 1, {"to_username": "bob", "amount": 100}, "duplicate"
                    )[0],
                    range(16),
                )
            )
        assert len({r["transfer_id"] for r in results}) == 1

        def opposite(i):
            return transfer_money(
                factory,
                1 if i % 2 == 0 else 2,
                {"to_username": "bob" if i % 2 == 0 else "alice", "amount": 10},
                f"opposite-{i}",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(opposite, range(40)))
        with factory() as db:
            assert db.get(User, 1).balance == 9900
            assert db.get(User, 2).balance == 10100
            assert db.scalar(select(func.count()).select_from(Transfer)) == 41
    finally:
        with engine.begin() as c:
            c.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        engine.dispose()
