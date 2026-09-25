"""Run against a lab API; creates two test users, makes a transfer and retries it."""

import argparse
import json
import uuid
import httpx


def run(base):
    with httpx.Client(base_url=base, timeout=45) as c:

        def req(method, path, body=None, headers=None):
            r = c.request(method, path, json=body, headers=headers)
            r.raise_for_status()
            return r.json()

        suffix = uuid.uuid4().hex[:10]
        users = [f"smoke_a_{suffix}", f"smoke_b_{suffix}"]
        for user in users:
            req(
                "POST",
                "/api/auth/register",
                {"username": user, "password": "SmokePass123!"},
            )
        login = req(
            "POST",
            "/api/auth/login",
            {"username": users[0], "password": "SmokePass123!"},
        )
        headers = {"X-Session": login["session"], "Idempotency-Key": uuid.uuid4().hex}
        before = req("GET", "/api/account/me", headers=headers)["balance"]
        body = {"to_username": users[1], "amount": 123}
        first = req("POST", "/api/transfer/transfer", body, headers)
        second = req("POST", "/api/transfer/transfer", body, headers)
        assert first["transfer_id"] == second["transfer_id"]
        assert req("GET", "/api/account/me", headers=headers)["balance"] == before - 123
        assert req("GET", "/api/notifications/notifications", headers=headers)
        req("POST", "/api/auth/logout", headers=headers)
        assert c.get("/api/account/me", headers=headers).status_code == 401
        return {
            "smoke": "passed",
            "duplicate_retry": "passed",
            "logout": "passed",
            "transfer_id": first["transfer_id"],
        }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    args = p.parse_args()
    print(json.dumps(run(args.base_url), indent=2))
