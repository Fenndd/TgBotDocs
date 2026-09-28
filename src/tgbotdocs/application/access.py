"""Shared-password protection; sessions and attempt counters stay in RAM."""

from collections import deque
from dataclasses import dataclass
import hmac
import time


@dataclass(frozen=True)
class PasswordAttempt:
    success: bool
    locked: bool = False
    retry_after_s: float = 0.0
    operator_alert: bool = False


class AccessGuard:
    def __init__(self, password, *, attempts=5, window_s=900.0, global_surge=30, clock=time.monotonic):
        self._password = password.encode("utf-8")
        self.attempts, self.window_s, self.global_surge, self.clock = attempts, window_s, global_surge, clock
        self._failures, self._global = {}, deque()
        self._alert_at = None

    def attempt(self, owner, candidate):
        now = self.clock()
        user = self._failures.setdefault(owner, deque())
        for window in (user, self._global):
            while window and window[0] <= now - self.window_s:
                window.popleft()
        if len(user) >= self.attempts:
            # Still compare in constant time; a correct entry cannot bypass the
            # configured per-user pause, and it never causes a global pause.
            hmac.compare_digest(candidate.encode("utf-8"), self._password)
            return PasswordAttempt(False, True, max(0.0, user[0] + self.window_s - now))
        if hmac.compare_digest(candidate.encode("utf-8"), self._password):
            self._failures.pop(owner, None)
            return PasswordAttempt(True)
        user.append(now)
        self._global.append(now)
        alert = len(self._global) >= self.global_surge and (
            self._alert_at is None or self._alert_at <= now - self.window_s)
        if alert:
            self._alert_at = now
        locked = len(user) >= self.attempts
        return PasswordAttempt(False, locked, max(0.0, user[0] + self.window_s - now) if locked else 0.0, alert)

    def prune(self):
        now = self.clock()
        for owner, attempts in tuple(self._failures.items()):
            while attempts and attempts[0] <= now - self.window_s:
                attempts.popleft()
            if not attempts:
                self._failures.pop(owner, None)
