<#
.SYNOPSIS
    One-time local setup: create .venv, install dependencies, seed .env.

.DESCRIPTION
    Does not touch your .env if it already exists. After it finishes, edit .env
    (BOT_TOKEN, ADMIN_IDS, and the Turnstile keys if you want the captcha) and
    start the bot with:  .venv\Scripts\python.exe -m bot

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy/setup.ps1
#>
[CmdletBinding()]
param([switch]$ForceEnv)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "python not found in PATH (3.11+ required)" }
$version = & $python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]::Parse($version) -lt [version]'3.11') { throw "Python 3.11+ required, found $version" }

if (-not (Test-Path '.venv')) {
    Write-Host "-> creating .venv"
    & $python -m venv .venv
}
$venvPy = Join-Path $root '.venv/Scripts/python.exe'
Write-Host "-> installing dependencies"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
Write-Host "-> dependencies installed"

if (-not (Test-Path '.env') -or $ForceEnv) {
    Copy-Item '.env.example' '.env'
    Write-Host "-> .env created from .env.example - fill in BOT_TOKEN and ADMIN_IDS" -ForegroundColor Yellow
} else {
    Write-Host "-> .env already exists, left untouched"
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  1. edit .env (BOT_TOKEN from @BotFather, ADMIN_IDS = your numeric id)"
Write-Host "  2. start:  .venv\Scripts\python.exe -m bot"
Write-Host "  3. tests:  .venv\Scripts\python.exe -m pytest -q"
