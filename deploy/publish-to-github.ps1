<#
.SYNOPSIS
    Publish this repository to your own GitHub account.

.DESCRIPTION
    Two ways, picked automatically:

    1. gh CLI installed and logged in -> it creates the repository for you.
    2. No gh CLI -> the repository must already exist and be empty; this script
       pushes to it and Git Credential Manager opens a browser window so you can
       sign in. No token is ever typed into a terminal or written to disk.

    Run it from the session folder:
        powershell -ExecutionPolicy Bypass -File deploy/publish-to-github.ps1

.PARAMETER User
    GitHub account name. Defaults to canucome.

.PARAMETER Repo
    Repository name. Defaults to tg-giveaway-bot.

.PARAMETER RepoPath
    The working copy to publish. Auto-detected when omitted.

.PARAMETER Private
    Create the repository as private instead of public.

.PARAMETER CheckOnly
    Report what would happen and exit without touching anything.
#>
[CmdletBinding()]
param(
    [string]$User = 'canucome',
    [string]$Repo = 'tg-giveaway-bot',
    [string]$RepoPath = '',
    [switch]$Private,
    [switch]$CheckOnly
)

# Native commands (git) write progress to stderr, which PowerShell 5 turns into
# a terminating error under 'Stop'. Everything is checked through $LASTEXITCODE.
$ErrorActionPreference = 'Continue'

function Fail([string]$Message, [string]$Hint) {
    Write-Host "x $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "  $Hint" -ForegroundColor Yellow }
    exit 1
}

function Find-Repo([string]$Start) {
    $dir = [System.IO.DirectoryInfo](Resolve-Path $Start).Path
    while ($dir) {
        if (Test-Path (Join-Path $dir.FullName '.git')) { return $dir.FullName }
        $dir = $dir.Parent
    }
    return $null
}

$root = $null
if ($RepoPath) {
    $root = Find-Repo $RepoPath
} else {
    $root = Find-Repo $PSScriptRoot
    if (-not $root) {
        # Session layout: deploy/ sits next to the checkout, not inside it.
        $sibling = Join-Path (Split-Path $PSScriptRoot -Parent) 'tg-giveaway-bot'
        if (Test-Path $sibling) { $root = Find-Repo $sibling }
    }
}
if (-not $root) { Fail "could not find a git checkout" "Pass -RepoPath <path to the working copy>." }

$branch = (& git -C $root branch --show-current).Trim()
if (-not $branch) { Fail "no branch checked out (detached HEAD?)" }

$dirty = @(& git -C $root status --porcelain).Count
$url = "https://github.com/$User/$Repo"

Write-Host "repository : $root"
Write-Host "branch     : $branch"
Write-Host "target     : $url"
if ($dirty -gt 0) { Write-Host "! $dirty uncommitted change(s) will NOT be pushed" -ForegroundColor Yellow }
Write-Host ""

# --- does the remote repository exist? ---------------------------------------
$exists = $false
try {
    $probe = Invoke-WebRequest -Uri "https://api.github.com/repos/$User/$Repo" -UseBasicParsing -TimeoutSec 20
    $exists = ($probe.StatusCode -eq 200)
} catch {
    $exists = $false
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
$ghReady = $false
if ($gh) {
    & gh auth status *> $null
    $ghReady = ($LASTEXITCODE -eq 0)
}

if ($exists) {
    Write-Host "-> $User/$Repo exists on GitHub; pushing into it." -ForegroundColor Cyan
    if (-not $CheckOnly) {
        & git -C $root remote remove origin *> $null
        & git -C $root remote add origin "$url.git"
        Write-Host "-> pushing (a browser window may open for GitHub sign-in)..." -ForegroundColor Cyan
        & git -C $root push -u origin $branch
        if ($LASTEXITCODE -ne 0) {
            Fail "push failed" "If the repository already has commits, run: git -C \"$root\" pull origin $branch --rebase"
        }
        Write-Host "-> done: $url" -ForegroundColor Green
    }
}
elseif ($ghReady) {
    Write-Host "-> creating $User/$Repo with gh, then pushing." -ForegroundColor Cyan
    if (-not $CheckOnly) {
        $visibility = if ($Private) { '--private' } else { '--public' }
        Push-Location $root
        & gh repo create "$User/$Repo" $visibility --source . --remote origin --push
        $code = $LASTEXITCODE
        Pop-Location
        if ($code -ne 0) { Fail "gh repo create failed" }
        Write-Host "-> done: $url" -ForegroundColor Green
    }
}
else {
    $vis = if ($Private) { 'private' } else { 'public' }
    Write-Host "x $User/$Repo does not exist yet, and gh CLI is not installed/authenticated." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Step 1 - create the empty repository (leave README/.gitignore unchecked):" -ForegroundColor Yellow
    Write-Host "    https://github.com/new?name=$Repo&visibility=$vis" -ForegroundColor Yellow
    Write-Host "  Step 2 - run this script again; the browser will ask you to sign in." -ForegroundColor Yellow
    exit 2
}

if ($CheckOnly) { Write-Host "(check only - nothing was changed)" -ForegroundColor DarkGray }
