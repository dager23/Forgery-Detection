"""Password hashing, JWT issuing/verification and login throttling."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

ALGORITHM = "HS256"
# bcrypt only uses the first 72 bytes; reject longer passwords instead of silently truncating
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# Constant-time dummy check so unknown emails take as long as wrong passwords
_DUMMY_HASH = hash_password("docauth-timing-equaliser")


def dummy_verify() -> None:
    verify_password("x", _DUMMY_HASH)


def create_token(user_id: int, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=ttl_minutes)}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> int | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp"]})
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class LoginThrottle:
    """Sliding-window limiter for failed logins, keyed by (email, client ip)."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        with self._lock:
            now = time.monotonic()
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - q[0])))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
