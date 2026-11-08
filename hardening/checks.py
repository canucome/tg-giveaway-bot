"""额外的反作弊组件：账号年龄闸门 / 验证页限速 / 可复算开奖。

这些函数与 tg-giveaway-bot 解耦，接线点见文件末尾注释。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 账号年龄
# Telegram 的用户 ID 是单调递增分配的，ID 越小 = 注册越早。
# 用一个阈值就能挡掉「刚注册的一批小号」，比任何前端 captcha 都硬。
def account_age_gate(user_id: int, min_user_id: int) -> bool:
    """user_id 低于阈值视为新号，拒绝报名。"""
    return int(user_id) >= int(min_user_id)


# ---------------------------------------------------------------- 限速
@dataclass
class IpRateLimiter:
    """每 IP 每分钟次数上限（滑动窗口）。单进程内存实现，够挡住脚本刷验证页。"""

    per_minute: int = 20
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, ip: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        window = [t for t in self._hits.get(ip, []) if now - t < 60.0]
        if len(window) >= self.per_minute:
            self._hits[ip] = window
            return False
        window.append(now)
        self._hits[ip] = window
        return True


# ---------------------------------------------------------------- 可复算开奖
def make_commit() -> tuple[str, str]:
    """开奖前公布 commit=sha256(seed)，开奖后公布 seed；任何人都能复算名次。"""
    seed = secrets.token_hex(32)
    return seed, hashlib.sha256(seed.encode()).hexdigest()


def reveal_ok(seed: str, commit: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(seed.encode()).hexdigest(), commit)


def _keystream(seed: str, counter: int) -> bytes:
    return hashlib.sha256(f"{seed}:{counter}".encode()).digest()


def draw_indices(seed: str, n: int, k: int) -> list[int]:
    """从 n 个参与者里确定性地抽 k 个不重复下标（Fisher-Yates + sha256 流）。

    seed + n 相同 => 结果必然相同，参与者可以自己验算抽奖是否被动过手脚。
    """
    if n <= 0 or k <= 0:
        return []
    idx = list(range(n))
    counter = 0
    for i in range(min(k, n)):
        counter += 1
        r = int.from_bytes(_keystream(seed, counter), "big")
        j = i + r % (n - i)
        idx[i], idx[j] = idx[j], idx[i]
    return idx[: min(k, n)]


# ---------------------------------------------------------------- 接线点
# 1) bot/handlers/participate.py，on_join 开头（第 34 行 uid 之后）：
#       from hardening.checks import account_age_gate
#       MIN_UID = 5_000_000_000          # 2021 年后注册的号
#       if not account_age_gate(uid, MIN_UID):
#           await cq.answer("账号太新，暂不能参加", show_alert=True); return
# 2) bot/web/verify.py，POST /verify 分支开头：
#       from hardening.checks import IpRateLimiter
#       LIMITER = IpRateLimiter(per_minute=10)
#       if not LIMITER.allow(request.remote or "?"):
#           raise web.HTTPTooManyRequests(text="too many attempts")
# 3) pytest 里断言 draw_indices 可复算（见 hardening/test_checks.py）。
