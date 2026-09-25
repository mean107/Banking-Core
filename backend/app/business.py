import hashlib
import json
import re
import uuid
import bcrypt
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from .db import User, Transfer, Notification, Receipt


def transfer_money(factory, user_id, payload, key):
    amount = payload.get("amount")
    recipient = payload.get("to_username")
    if type(amount) is not int or not 0 < amount <= 10**12:
        raise HTTPException(400, "Amount must be a positive integer <= 1000000000000")
    if not isinstance(recipient, str) or not recipient.strip():
        raise HTTPException(400, "Recipient is required")
    recipient = recipient.strip()
    fingerprint = hashlib.sha256(json.dumps([recipient, amount]).encode()).hexdigest()
    receipt_key = f"{user_id}:{key}"
    with factory.begin() as db:
        if db.bind.dialect.name == "postgresql":
            # Serialize the same idempotency key even if recipient changes on retry.
            lock = int.from_bytes(
                hashlib.sha256(receipt_key.encode()).digest()[:8], "big", signed=True
            )
            db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
        existing = db.get(Receipt, receipt_key)
        if existing:
            if existing.fingerprint != fingerprint:
                raise HTTPException(
                    409, "Idempotency key reused with different payload"
                )
            return existing.result, None
        receiver_id = db.scalar(select(User.id).where(User.username == recipient))
        if receiver_id is None:
            raise HTTPException(404, "Recipient not found")
        if receiver_id == user_id:
            raise HTTPException(400, "Cannot transfer to yourself")
        # Always lock accounts in ascending ID order to avoid opposite-transfer deadlocks.
        users = db.scalars(
            select(User)
            .where(User.id.in_([user_id, receiver_id]))
            .order_by(User.id)
            .with_for_update()
        ).all()
        accounts = {u.id: u for u in users}
        if user_id not in accounts:
            raise HTTPException(404, "Sender not found")
        sender, receiver = accounts[user_id], accounts[receiver_id]
        if sender.balance < amount:
            raise HTTPException(400, "Insufficient balance")
        sender.balance -= amount
        receiver.balance += amount
        record = Transfer(sender_id=user_id, receiver_id=receiver_id, amount=amount)
        db.add(record)
        message = f"Bạn nhận {amount} từ {sender.username}"
        db.add_all(
            [
                Notification(
                    user_id=user_id, message=f"Bạn đã chuyển {amount} đến {recipient}"
                ),
                Notification(user_id=receiver_id, message=message),
            ]
        )
        db.flush()
        result = {
            "ok": True,
            "from": sender.username,
            "to": recipient,
            "amount": amount,
            "transfer_id": record.id,
        }
        db.add(Receipt(key=receipt_key, fingerprint=fingerprint, result=result))
        return result, (receiver_id, message)


async def dispatch(role, action, payload, session, key, redis, factory):
    import asyncio

    if role == "auth" and action in ("register", "login"):
        username, password = payload.get("username"), payload.get("password")
        if not isinstance(username, str) or not re.fullmatch(
            r"[A-Za-z0-9_]{3,50}", username
        ):
            raise HTTPException(400, "Username: 3-50 letters, numbers or underscore")
        if not isinstance(password, str) or not 6 <= len(password.encode()) <= 72:
            raise HTTPException(400, "Password: 6-72 UTF-8 bytes")

        def authenticate():
            with factory.begin() as db:
                user = db.scalar(select(User).where(User.username == username))
                if action == "register":
                    if user:
                        raise HTTPException(409, "Username already exists")
                    user = User(
                        username=username,
                        password_hash=bcrypt.hashpw(
                            password.encode(), bcrypt.gensalt()
                        ).decode(),
                    )
                    db.add(user)
                    try:
                        db.flush()
                    except IntegrityError:
                        raise HTTPException(409, "Username already exists")
                elif not user or not bcrypt.checkpw(
                    password.encode(), user.password_hash.encode()
                ):
                    raise HTTPException(401, "Invalid credentials")
                return {
                    "id": user.id,
                    "username": user.username,
                    "balance": user.balance,
                }

        result = await asyncio.to_thread(authenticate)
        if action == "login":
            sid = uuid.uuid4().hex
            await redis.setex(f"session:{sid}", 86400, str(result["id"]))
            result["session"] = sid
        return result
    user_id = await redis.get(f"session:{session}") if session else None
    if not user_id:
        raise HTTPException(401, "Invalid/expired session")
    user_id = int(user_id)
    if role == "auth" and action == "logout":
        await redis.delete(f"session:{session}")
        return {"ok": True}
    if role == "transfer" and action == "transfer":
        result, notification = await asyncio.to_thread(
            transfer_money, factory, user_id, payload, key
        )
        if notification:
            try:
                await redis.publish(f"notify:{notification[0]}", notification[1])
            except Exception:
                # PostgreSQL notification remains available; a push failure cannot undo money.
                import logging

                logging.getLogger("banking").warning(
                    "notification_push_failed transfer_id=%s", result["transfer_id"]
                )
        return result

    def query():
        with factory() as db:
            if role == "account" and action in ("me", "balance"):
                u = db.get(User, user_id)
                if not u:
                    raise HTTPException(404, "User not found")
                return {"id": u.id, "username": u.username, "balance": u.balance}
            if role == "notification" and action == "notifications":
                rows = db.scalars(
                    select(Notification)
                    .where(Notification.user_id == user_id)
                    .order_by(Notification.id.desc())
                    .limit(50)
                ).all()
                return [
                    {
                        "id": n.id,
                        "message": n.message,
                        "created_at": n.created_at.isoformat(),
                    }
                    for n in rows
                ]
        raise HTTPException(404, "Unknown action")

    return await asyncio.to_thread(query)
