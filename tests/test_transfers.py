import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base, User, Transfer, Notification
from app.business import transfer_money


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all(
            [
                User(id=1, username="alice", password_hash="unused", balance=1000),
                User(id=2, username="bob", password_hash="unused", balance=1000),
            ]
        )
    yield factory
    engine.dispose()


def test_transfer_conserves_money_and_persists_notifications(factory):
    result, notify = transfer_money(
        factory, 1, {"to_username": "bob", "amount": 250}, "one"
    )
    assert result["amount"] == 250 and notify[0] == 2
    with factory() as db:
        assert db.get(User, 1).balance == 750
        assert db.get(User, 2).balance == 1250
        assert db.scalar(select(func.count()).select_from(Transfer)) == 1
        assert db.scalar(select(func.count()).select_from(Notification)) == 2


def test_retry_does_not_debit_twice(factory):
    args = (factory, 1, {"to_username": "bob", "amount": 250}, "same")
    first, _ = transfer_money(*args)
    second, notify = transfer_money(*args)
    assert first == second and notify is None
    with factory() as db:
        assert db.get(User, 1).balance == 750


def test_key_cannot_change_payload(factory):
    transfer_money(factory, 1, {"to_username": "bob", "amount": 100}, "same")
    with pytest.raises(HTTPException) as exc:
        transfer_money(factory, 1, {"to_username": "bob", "amount": 200}, "same")
    assert exc.value.status_code == 409


@pytest.mark.parametrize("amount", [0, -1, 1.2, True, "100", None, 10**12 + 1])
def test_invalid_amount(factory, amount):
    with pytest.raises(HTTPException):
        transfer_money(factory, 1, {"to_username": "bob", "amount": amount}, "invalid")
    with factory() as db:
        assert db.get(User, 1).balance == 1000


@pytest.mark.parametrize(
    "recipient,amount", [("alice", 10), ("missing", 10), ("bob", 1001)]
)
def test_rejected_transfer_is_atomic(factory, recipient, amount):
    with pytest.raises(HTTPException):
        transfer_money(
            factory, 1, {"to_username": recipient, "amount": amount}, "reject"
        )
    with factory() as db:
        assert db.get(User, 1).balance == 1000
        assert db.scalar(select(func.count()).select_from(Transfer)) == 0
