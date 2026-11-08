# What this fork adds / 这个分支加了什么

Upstream: [Star-Dream-AI/telegram-giveaway-bot](https://github.com/Star-Dream-AI/telegram-giveaway-bot) (MIT).
This fork keeps the original code and adds one feature plus the packaging it needs:

## 1. Self-service prize delivery / 中奖者自助领取奖品

The prize is text — a redemption code, a key, or any message — so winners pull it from
the bot themselves and the host never sends a DM by hand.

- `Giveaway.prize_mode` (`none` / `unique` / `shared`) plus two new tables,
  `prize_codes` (stock: one row per code, `max_claims`, `claimed_count`) and
  `prize_claims` (who claimed which code, unique per `giveaway_id + user_id + tier`).
- Atomic claim: `UPDATE prize_codes SET claimed_count = claimed_count + 1
  WHERE id = ? AND claimed_count < max_claims` with a `rowcount` check and a
  bounded retry, so one code can never reach two people.
- Winner DMs carry a **🎁 Claim prize** button (`ClaimCb`, tier by index to stay
  under Telegram's 64-byte `callback_data` limit); `/claim <id>` claims every
  unclaimed tier at once and `/myprizes` re-shows what was already delivered.
- Host tools: `/addcodes <id> <tier>` tops up stock (one prize per line),
  `/prizestatus <id>` shows total / claimed / remaining. When a tier runs dry the
  winner is told, and the host is pinged once with the exact `/addcodes` command.
- The `/newgiveaway` wizard grew from 7 to 9 steps: *how to deliver* and *paste the
  codes*. Old databases are upgraded in place by a lightweight
  `ALTER TABLE giveaways ADD COLUMN prize_mode ...` migration.

## 2. Anti-abuse gates, wired in and on by default / 反滥用三件套

The three helpers that used to sit unused in `hardening/` are now part of the
request path; `hardening/checks.py` just re-exports them from
`bot/utils/antiabuse.py`.

| Gate | Where | Default | Knob |
|---|---|---|---|
| Account-age (user-id floor) | `bot/handlers/participate.py` before any DB work | on | `ACCOUNT_AGE_GATE`, `MIN_USER_ID` |
| Per-IP budget on the verification page | `bot/web/verify.py` `_enforce_rate_limit()` | on | `VERIFY_RATE_PER_MINUTE`, `TRUST_FORWARDED_FOR` |
| Commit-reveal draw | seed created in `services/giveaway.create`, `sha256(seed)` printed in the post, seed revealed in the announcement | on | always on |

`MIN_USER_ID=0` keeps the gate armed but does not filter, because a blind
threshold can block a real audience. `/gate [giveaway_id]` prints the current
policy and the user-id spread of that giveaway's participants so the number can
be chosen from data.

## 3. Packaging / 打包

- `.env.example` — the README told you to copy it, but it was missing.
- `.gitignore` — `__pycache__`, `.venv`, `data/`, `.env` and SQLite files stay out of git.
- `hardening/` — standalone copies of the same helpers plus their tests; the bot
  imports the implementations from `bot/utils/antiabuse.py`.

## Tests / 测试

```bash
pip install -r requirements.txt pytest pytest-asyncio
pytest                 # 105 tests
pytest hardening       # 5 extra checks (standalone)
```

105 tests = 94 from upstream + 7 prize tests + 4 wizard tests. No Telegram or
Cloudflare network access is required.