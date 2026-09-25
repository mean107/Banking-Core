import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
import aio_pika
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from opentelemetry.propagate import inject, extract
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from .business import dispatch
from .db import make_engine
from .telemetry import setup, REQUESTS, LATENCY, PROCESSED

ROLE = os.getenv("ROLE", "api")
TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "30"))
ROUTES = {
    ("POST", "/api/auth/register"): ("auth", "register"),
    ("POST", "/api/auth/login"): ("auth", "login"),
    ("POST", "/api/auth/logout"): ("auth", "logout"),
    ("GET", "/api/account/me"): ("account", "me"),
    ("GET", "/api/account/balance"): ("account", "balance"),
    ("POST", "/api/transfer/transfer"): ("transfer", "transfer"),
    ("GET", "/api/notifications/notifications"): ("notification", "notifications"),
}


async def redis_client():
    hosts = os.getenv("REDIS_SENTINELS")
    if hosts:
        nodes = [(h.split(":")[0], int(h.split(":")[1])) for h in hosts.split(",")]
        password = os.environ["REDIS_PASSWORD"]
        sentinel = Sentinel(
            nodes,
            sentinel_kwargs={"password": password},
            password=password,
            decode_responses=True,
            socket_timeout=3,
        )
        return sentinel.master_for("banking")
    return Redis.from_url(
        os.environ["REDIS_URL"], decode_responses=True, socket_timeout=3
    )


async def process(message):
    async with message.process(requeue=True):
        data = json.loads(message.body)
        with tracer.start_as_current_span(
            f"{ROLE}.process", context=extract(data.get("trace", {}))
        ):
            try:
                value = await dispatch(
                    ROLE,
                    data["action"],
                    data["payload"],
                    data["session"],
                    data["key"],
                    app.state.redis,
                    app.state.factory,
                )
                result = {"status": 200, "body": value}
            except HTTPException as e:
                result = {"status": e.status_code, "body": {"detail": e.detail}}
            except Exception:
                # Let RabbitMQ requeue infrastructure failures. Small backoff avoids busy loops.
                logger.exception(
                    "consumer_failure correlation_id=%s", data["correlation_id"]
                )
                await asyncio.sleep(1)
                raise
            await app.state.redis.setex(
                f"response:{data['correlation_id']}", 120, json.dumps(result)
            )
            PROCESSED.labels(ROLE, str(result["status"])).inc()
            logger.info(
                "consumer_completed correlation_id=%s status=%s",
                data["correlation_id"],
                result["status"],
            )


@asynccontextmanager
async def lifespan(app):
    if ROLE not in {"api", "auth", "account", "transfer", "notification"}:
        raise RuntimeError("Invalid ROLE")
    app.state.redis = await redis_client()
    await app.state.redis.ping()
    app.state.rmq = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    app.state.channel = await app.state.rmq.channel(publisher_confirms=True)
    await app.state.channel.set_qos(prefetch_count=8)
    for role in ("auth", "account", "transfer", "notification"):
        queue = await app.state.channel.declare_queue(
            f"{role}.requests",
            durable=True,
            arguments={"x-max-length": 10000, "x-overflow": "reject-publish"},
        )
        if ROLE == role:
            app.state.engine = make_engine()
            app.state.factory = sessionmaker(app.state.engine, expire_on_commit=False)
            app.state.queue = queue
            app.state.consumer_tag = await queue.consume(process)
    yield
    if hasattr(app.state, "queue"):
        await app.state.queue.cancel(app.state.consumer_tag)
    await app.state.rmq.close()
    await app.state.redis.aclose()
    if hasattr(app.state, "engine"):
        app.state.engine.dispose()
    provider.shutdown()


app = FastAPI(title=f"Banking Core: {ROLE}", lifespan=lifespan)
tracer, logger, provider = setup(app, ROLE)


@app.get("/health")
async def health():
    return {"status": "alive", "role": ROLE}


@app.get("/ready")
async def ready():
    try:
        await app.state.redis.ping()
        if app.state.rmq.is_closed or not app.state.rmq.connected.is_set():
            raise RuntimeError("RabbitMQ unavailable")
        if hasattr(app.state, "engine"):

            def ping():
                with app.state.engine.connect() as db:
                    db.execute(text("SELECT 1"))

            await asyncio.to_thread(ping)
        return {"status": "ready"}
    except Exception:
        return JSONResponse({"status": "not_ready"}, status_code=503)


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    route = ROUTES.get((request.method, request.url.path))
    if ROLE != "api" or route is None:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    start, status = time.monotonic(), 500
    try:
        raw = await request.body()
        if len(raw) > 16384:
            raise HTTPException(413, "Request too large")
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(payload, dict):
            raise HTTPException(400, "JSON object required")
        correlation_id = str(uuid.uuid4())
        key = request.headers.get("Idempotency-Key", correlation_id)
        if not 1 <= len(key) <= 100:
            raise HTTPException(400, "Idempotency-Key must contain 1-100 characters")
        carrier = {}
        inject(carrier)
        body = {
            "action": route[1],
            "payload": payload,
            "session": request.headers.get("X-Session", ""),
            "key": key,
            "correlation_id": correlation_id,
            "trace": carrier,
        }
        message = aio_pika.Message(
            json.dumps(body).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            expiration=timedelta(seconds=TIMEOUT),
            correlation_id=correlation_id,
        )
        await app.state.channel.default_exchange.publish(
            message, routing_key=f"{route[0]}.requests", timeout=5
        )
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            result = await app.state.redis.getdel(f"response:{correlation_id}")
            if result:
                result = json.loads(result)
                status = result["status"]
                return JSONResponse(
                    result["body"],
                    status_code=status,
                    headers={
                        "X-Correlation-Id": correlation_id,
                        "Idempotency-Key": key,
                    },
                )
            await asyncio.sleep(0.1)
        raise HTTPException(
            504,
            "Processing timed out; transfer outcome may be unknown. Retry with the SAME Idempotency-Key.",
        )
    except HTTPException as e:
        status = e.status_code
        return JSONResponse({"detail": e.detail}, status_code=status)
    except Exception:
        status = 503
        logger.exception("producer_unavailable")
        return JSONResponse(
            {
                "detail": "Dependency unavailable; retry transfer with the SAME Idempotency-Key"
            },
            status_code=status,
        )
    finally:
        REQUESTS.labels(ROLE, request.url.path, str(status)).inc()
        LATENCY.labels(ROLE, request.url.path).observe(time.monotonic() - start)
        logger.info("request_completed route=%s status=%s", request.url.path, status)


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    session = ws.query_params.get("session", "")
    user_id = (
        await app.state.redis.get(f"session:{session}")
        if ROLE == "notification"
        else None
    )
    if not user_id:
        await ws.close(code=1008)
        return
    await ws.accept()
    async with app.state.redis.pubsub() as pubsub:
        await pubsub.subscribe(f"notify:{user_id}")

        async def listen():
            while True:
                await ws.receive_text()

        receiver = asyncio.create_task(listen())
        try:
            while not receiver.done():
                if not await app.state.redis.exists(f"session:{session}"):
                    await ws.close(code=1008)
                    break
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1
                )
                if msg and msg["type"] == "message":
                    await ws.send_json({"type": "notification", "message": msg["data"]})
                await asyncio.sleep(0.05)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            receiver.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await receiver
