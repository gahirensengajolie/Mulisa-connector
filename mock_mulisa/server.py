"""Local stand-in for Mulisa's POST /api/screen, built from the public OpenAPI contract.

Behaviour
  * flags a payment whose amount (minor units) is above MOCK_FLAG_THRESHOLD_MINOR
  * flags a payment to/from a blacklisted account (MOCK_BLACKLIST, comma separated)
  * clears everything else
  * treats transaction.id as an idempotency key: a repeat returns the ORIGINAL result with 200
  * can be made slow or failing on purpose, at runtime, with POST /__control

Test helpers (not part of Mulisa): POST /__control, POST /__reset, GET /__stats.
Run:  python -m mock_mulisa.server        (env: MOCK_PORT, MOCK_API_KEY, ...)
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = (
    "normal",
    "slow",  # every call is delayed by `delay` seconds
    "flaky_once",  # the first call per transaction.id is delayed, repeats are fast
    "error_503",  # 503, retryable: true
    "error_503_once",  # first call per id: 503 retryable, repeats succeed
    "error_500",  # 500, retryable: false
    "error_400",  # 400 validation error, retryable: false
    "bad_status",  # 200 with a status value nobody knows
    "garbage",  # 200 with a body that is not JSON
)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.mode = os.environ.get("MOCK_MODE", "normal")
            self.delay = float(os.environ.get("MOCK_DELAY_SECONDS", "1.0"))
            self.results: dict = {}  # transaction.id -> response (idempotency)
            self.processed = 0  # distinct screenings actually performed
            self.received: list = []  # transaction.id of EVERY request received, in order
            self.bodies: list = []  # the full request bodies, so tests can inspect what was sent
            self.attempts: dict = {}  # transaction.id -> number of requests seen


def _envelope(code: str, message: str, retryable: bool, details=None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": "req_" + uuid.uuid4().hex[:12],
            "retryable": retryable,
            "details": details or [],
            "docs_url": "https://mulisa.jengacore.com/docs/errors",
        }
    }


def _validate(body) -> list:
    """Check the fields the connector must send. Mirrors the contract's example request."""
    problems = []
    if not isinstance(body, dict):
        return ["body must be an object"]
    tx, sender, receiver = (
        body.get("transaction"),
        body.get("sender"),
        body.get("receiver"),
    )
    if not isinstance(tx, dict):
        problems.append("transaction is required")
    else:
        if not isinstance(tx.get("id"), str) or not tx["id"]:
            problems.append("transaction.id is required")
        amount = tx.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            problems.append("transaction.amount must be a positive integer (minor units)")
        if not isinstance(tx.get("currency"), str) or len(tx["currency"]) != 3:
            problems.append("transaction.currency must be a 3-letter code")
        if not isinstance(tx.get("timestamp"), str):
            problems.append("transaction.timestamp is required")
    for label, party in (("sender", sender), ("receiver", receiver)):
        if not isinstance(party, dict):
            problems.append(f"{label} is required")
        elif not isinstance(party.get("account"), str) or not party["account"]:
            problems.append(f"{label}.account is required")
    return problems


def _decide(body: dict) -> dict:
    threshold = int(os.environ.get("MOCK_FLAG_THRESHOLD_MINOR", "1000000"))
    raw_blacklist = os.environ.get("MOCK_BLACKLIST", "250722000999,GB-9999")
    blacklist = {item.strip() for item in raw_blacklist.split(",") if item.strip()}
    tx, sender, receiver = body["transaction"], body["sender"], body["receiver"]

    hits = [acc for acc in (sender["account"], receiver["account"]) if acc in blacklist]
    high_value = tx["amount"] > threshold
    flagged = bool(hits) or high_value
    if hits:
        risk, confidence = 1.0, 1.0
    elif high_value:
        risk, confidence = 0.82, 0.82
    else:
        risk, confidence = 0.05, 0.95
    return {
        "screening_id": "scr_" + uuid.uuid4().hex[:8],
        "status": "flagged" if flagged else "cleared",
        "confidence": confidence,
        "risk_score": risk,
        "risk_threshold": 0.6,
        "rule_results": [
            {
                "rule_id": "high-value-transfer",
                "name": "High-value transfer",
                "matched": high_value,
                "weight": 0.7,
                "severity": "high",
                "detail": "Amount above the review threshold.",
            }
        ],
        "model_score": 0.1,
        "blacklist_hits": hits,
        "latency_ms": 3,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def make_handler(state: State, api_key: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mock-mulisa"
        sys_version = ""

        def log_message(self, *args):
            pass

        def _json(self, status: int, body) -> None:
            data = json.dumps(body).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client gave up (a timeout, on purpose). Nothing to do.

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            try:
                return json.loads(self.rfile.read(length).decode("utf-8") or "null")
            except ValueError:
                return None

        def _authorised(self) -> bool:
            provided = self.headers.get("X-Api-Key") or ""
            auth = self.headers.get("Authorization", "")
            if not provided and auth[:7].lower() == "bearer ":
                provided = auth[7:].strip()
            return hmac.compare_digest(provided.encode(), api_key.encode())

        def do_GET(self):
            if self.path == "/__stats":
                with state.lock:
                    self._json(
                        200,
                        {
                            "mode": state.mode,
                            "processed": state.processed,
                            "requests": len(state.received),
                            "received_ids": list(state.received),
                            "bodies": list(state.bodies),
                        },
                    )
            elif self.path == "/api/health":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, _envelope("not_found", "no such endpoint", False))

        def do_POST(self):
            if self.path == "/__control":
                body = self._read_json() or {}
                mode = body.get("mode", "normal")
                if mode not in MODES:
                    return self._json(400, {"error": f"mode must be one of {list(MODES)}"})
                with state.lock:
                    state.mode = mode
                    if "delay" in body:
                        state.delay = float(body["delay"])
                return self._json(200, {"mode": state.mode, "delay": state.delay})
            if self.path == "/__reset":
                state.reset()
                return self._json(200, {"ok": True})
            if self.path != "/api/screen":
                return self._json(404, _envelope("not_found", "no such endpoint", False))

            if not self._authorised():
                return self._json(
                    401, _envelope("unauthorized", "missing or invalid API key", False)
                )
            body = self._read_json()
            problems = _validate(body)
            if problems:
                return self._json(
                    400,
                    _envelope("validation_error", "invalid request", False, problems),
                )

            txn_id = body["transaction"]["id"]
            with state.lock:
                state.received.append(txn_id)
                state.bodies.append(body)
                state.attempts[txn_id] = state.attempts.get(txn_id, 0) + 1
                attempt_no = state.attempts[txn_id]
                mode, delay = state.mode, state.delay

            if mode == "error_503" or (mode == "error_503_once" and attempt_no == 1):
                return self._json(503, _envelope("service_unavailable", "screening is busy", True))
            if mode == "error_500":
                return self._json(500, _envelope("internal_error", "unexpected failure", False))
            if mode == "error_400":
                return self._json(
                    400,
                    _envelope("validation_error", "invalid request", False, ["simulated"]),
                )
            if mode == "slow" or (mode == "flaky_once" and attempt_no == 1):
                time.sleep(delay)  # the work still completes below, like a real slow service

            with state.lock:  # idempotent: the first result for an id is the only one ever produced
                if txn_id not in state.results:
                    state.results[txn_id] = _decide(body)
                    state.processed += 1
                result = state.results[txn_id]

            if mode == "bad_status":
                return self._json(200, {**result, "status": "pending_review"})
            if mode == "garbage":
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", "9")
                    self.end_headers()
                    self.wfile.write(b"<html>oops")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self._json(200, result)

    return Handler


class MockServer(ThreadingHTTPServer):
    state: State


def make_server(
    host: str = "127.0.0.1", port: int = 0, api_key: str = "mock-mulisa-key-000000"
) -> MockServer:
    state = State()
    server = MockServer((host, port), make_handler(state, api_key))
    server.daemon_threads = True
    server.state = state
    return server


def main() -> int:
    port = int(os.environ.get("MOCK_PORT", "9100"))
    api_key = os.environ.get("MOCK_API_KEY", "mock-mulisa-key-000000")
    server = make_server(port=port, api_key=api_key)
    print(
        f"mock-mulisa listening on 127.0.0.1:{server.server_address[1]} mode={server.state.mode}",
        file=sys.stderr,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
