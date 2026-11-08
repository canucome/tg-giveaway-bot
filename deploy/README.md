# Deployment / 部署

Two ways to run this bot. Both need a `.env` in the repository root.

## A. Local / VPS without Docker

```powershell
powershell -ExecutionPolicy Bypass -File deploy/setup.ps1   # venv + deps + .env
# edit .env, then:
.venv\Scripts\python.exe -m bot
```

On Linux/macOS the equivalent is:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && $EDITOR .env
python -m bot
```

Long polling needs no public address. The captcha page does: set
`PUBLIC_BASE_URL` to a URL that reaches this machine (see below).

## B. Docker + automatic HTTPS

```bash
cp .env.example .env && $EDITOR .env      # WEBHOOK_BASE_URL=https://<DOMAIN>
DOMAIN=giveaway.example.com docker compose -f deploy/docker-compose.yml up -d --build
```

No domain? Use a wildcard-DNS name for your public IP: `DOMAIN=1.2.3.4.nip.io`,
and set `WEBHOOK_BASE_URL` / `PUBLIC_BASE_URL` to `https://1.2.3.4.nip.io`.

Caddy terminates TLS and proxies to the bot on port 8080.

## Publishing your own copy

```powershell
powershell -ExecutionPolicy Bypass -File deploy/publish-to-github.ps1 -CheckOnly
powershell -ExecutionPolicy Bypass -File deploy/publish-to-github.ps1
```
