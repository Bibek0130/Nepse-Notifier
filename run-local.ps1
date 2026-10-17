<#
.SYNOPSIS
    Set up and start NEPSE Notifier on this computer. Needs only Python (3.12+),
    plus Node.js (LTS) for the dashboard. No Postgres, Redis or Docker.

.DESCRIPTION
    First run: creates backend\venv, installs packages, creates the database,
    asks you for an admin login, fetches today's prices, then downloads a year
    of history (this takes a while) and prints the first digest email.
    Every run after that: fetches the latest prices, which runs the analysis and
    prints the digest, then opens the dashboard.

    The Django server and the dashboard each start in their own window. Close
    those windows to stop them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run-local.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -SkipFetch

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -SetupEmail
    Asks for a Gmail address and app password, saves them in backend\.env and
    sends a test email. After that, digests are emailed instead of printed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -Subscribe you@gmail.com
#>
param(
    [int]$HistoryDays = 730,  # how much history to download while too little is saved
    [switch]$SkipFetch,       # start the servers without fetching new prices
    [switch]$NoServers,       # set up and fetch only; don't start the servers
    [switch]$SetupEmail,      # save Gmail login so digests are emailed, not printed
    [string]$Subscribe        # add this email address as a digest subscriber
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$onWindows = [System.Environment]::OSVersion.Platform -eq "Win32NT"
$env:DJANGO_SETTINGS_MODULE = "config.settings.local"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

function Run {
    # Run a program and stop the script if it fails.
    $exe, $rest = $args
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "Failed ($LASTEXITCODE): $($args -join ' ')" }
}

function Django {
    Push-Location $backend
    try { Run $python manage.py @args } finally { Pop-Location }
}

function DjangoValue($code) {
    # Print one value from inside Django, e.g. a count.
    Push-Location $backend
    # Windows PowerShell 5.1 turns redirected stderr (e.g. warnings) into errors.
    $ErrorActionPreference = "Continue"
    try {
        $out = & $python manage.py shell -c $code 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Could not read from the database" }
        return ($out | Select-Object -Last 1).Trim()
    } finally { Pop-Location }
}

# --- Python environment -------------------------------------------------------
$venv = Join-Path $backend "venv"
$python = if ($onWindows) { Join-Path $venv "Scripts\python.exe" } else { Join-Path $venv "bin/python" }
if (-not (Test-Path $python)) {
    $base = @("py", "python", "python3") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
    if (-not $base) { throw "Python not found. Install Python 3.12 or newer from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." }
    Step "Creating the Python environment (backend\venv)"
    Run $base -m venv $venv
}
Step "Installing Python packages"
Run $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $backend "requirements.txt")

# --- Database -----------------------------------------------------------------
Step "Preparing the database (backend\local.sqlite3)"
Django migrate --verbosity 0

# --- Email ------------------------------------------------------------------
$envFile = Join-Path $backend ".env"
$emailOn = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^\s*EMAIL_HOST\s*=\s*\S" -Quiet)
$interactive = -not [Console]::IsInputRedirected
if ($interactive -and -not $SetupEmail -and -not $emailOn) {
    $answer = Read-Host "`nDigests are not emailed yet, only printed here. Set up Gmail sending now? (y/n)"
    if ($answer -match "^\s*y") { $SetupEmail = $true }
}
if ($SetupEmail) {
    Step "Setting up Gmail for sending digests"
    Write-Host "Gmail needs an app password, not your normal password. Turn on 2-Step Verification,"
    Write-Host "then create one at https://myaccount.google.com/apppasswords and paste it below."
    $gmail = (Read-Host "Gmail address to send from").Trim()
    $secure = Read-Host "App password (16 letters)" -AsSecureString
    $appPassword = [System.Net.NetworkCredential]::new("", $secure).Password -replace "\s", ""
    if (-not $gmail -or -not $appPassword) { throw "Both the Gmail address and the app password are needed." }
    $settings = [ordered]@{
        EMAIL_HOST          = "smtp.gmail.com"
        EMAIL_PORT          = "587"
        EMAIL_USE_TLS       = "true"
        EMAIL_HOST_USER     = $gmail
        EMAIL_HOST_PASSWORD = $appPassword
        DEFAULT_FROM_EMAIL  = "NEPSE Notifier <$gmail>"
    }
    # Try the login first (environment variables win over backend\.env), and save it only if it works.
    foreach ($key in $settings.Keys) { Set-Item "env:$key" $settings[$key] }
    Step "Sending a test email to $gmail"
    Push-Location $backend
    try {
        & $python manage.py shell -c "from django.core.mail import send_mail; send_mail('NEPSE Notifier test', 'Email is working. Digests will arrive here.', None, ['$gmail'])"
        $sent = $LASTEXITCODE -eq 0
    } finally { Pop-Location }
    if (-not $sent) {
        foreach ($key in $settings.Keys) { Remove-Item "env:$key" -ErrorAction SilentlyContinue }
        throw "Could not send through Gmail (the reason is above). Nothing was saved. Check the address, the app password and the internet connection, then run the script again."
    }
    $kept = @()
    if (Test-Path $envFile) { $kept = @(Get-Content $envFile | Where-Object { $_ -notmatch "^\s*(EMAIL_\w+|DEFAULT_FROM_EMAIL)\s*=" }) }
    $lines = @($kept) + @($settings.Keys | ForEach-Object { "$_=$($settings[$_])" })
    [System.IO.File]::WriteAllLines($envFile, [string[]]$lines)
    Write-Host "Saved in backend\.env (kept out of git)."
    Write-Host "Test email sent. Check the inbox of $gmail." -ForegroundColor Green
}
$emailOn = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^\s*EMAIL_HOST\s*=\s*\S" -Quiet)

if ($interactive -and -not $Subscribe) {
    $count = DjangoValue "from modules.notifications.infrastructure.models import Subscriber; print(Subscriber.objects.filter(is_active=True).count())"
    if ($count -eq "0") { $Subscribe = (Read-Host "`nNo subscribers yet. Email address that should get the digests (leave blank to skip)").Trim() }
}
if ($Subscribe) {
    $address = $Subscribe.Trim()
    if ($address -notmatch "^[^@\s'`"]+@[^@\s'`"]+\.[^@\s'`"]+$") { throw "'$address' doesn't look like an email address." }
    $result = DjangoValue "from modules.notifications.infrastructure.models import Subscriber; s, new = Subscriber.objects.get_or_create(email='$address'); print('added' if new else 'already subscribed')"
    Write-Host "$address`: $result" -ForegroundColor Green
}

$admins = DjangoValue "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True).count())"
if ($admins -eq "0") {
    Step "Create an admin login. You'll use it at http://localhost:8000/admin to add email subscribers."
    Django createsuperuser
}

# --- Prices -------------------------------------------------------------------
# The quant strategies need about 240 sessions of history; download more while less is saved
# (at most once a day, in case the source simply has no more).
$sessions = (DjangoValue "from modules.marketdata.infrastructure.models import Candle; print(Candle.objects.filter(timeframe='1D').values('trading_date').distinct().count())") -as [int]
$backfilledToday = DjangoValue "from django.utils import timezone; from modules.marketdata.infrastructure.models import IngestionRun; print(IngestionRun.objects.filter(kind='backfill', started_at__date=timezone.localdate()).exists())"
if (-not $SkipFetch) {
    try {
        Step "Fetching today's prices, then analysing them"
        Django ingest_market --kind eod --force
        if ($sessions -lt 250 -and $backfilledToday -ne "True") {
            Step "Only $sessions days of prices saved; downloading $HistoryDays days of history for every stock. This takes a while; the digest prints at the end."
            Django backfill_history --days $HistoryDays
        }
    } catch {
        Write-Host "`nCould not fetch prices (is the internet working?). Starting with the data already saved." -ForegroundColor Yellow
    }
}

$subscribers = DjangoValue "from modules.notifications.infrastructure.models import Subscriber; print(Subscriber.objects.filter(is_active=True).count())"
if ($subscribers -eq "0") {
    Write-Host "`nNo email subscribers yet, so no digest was sent. Add yourself with -Subscribe you@example.com, then run this script again." -ForegroundColor Yellow
} elseif (-not $emailOn) {
    Write-Host "`nDigests print in this window instead of being emailed. Run with -SetupEmail once to send them through Gmail." -ForegroundColor Yellow
}

if ($NoServers) { return }

# --- Servers ------------------------------------------------------------------
function StartWindow($title, $dir, $command) {
    if ($onWindows) {
        $full = "`$Host.UI.RawUI.WindowTitle = '$title'; `$env:DJANGO_SETTINGS_MODULE = 'config.settings.local'; $command"
        Start-Process powershell -WorkingDirectory $dir -ArgumentList "-NoExit", "-Command", $full | Out-Null
    } else {
        Write-Host "Run in a new terminal:  cd '$dir' && $command"
    }
}

Step "Starting the Django server (admin and API) at http://localhost:8000"
StartWindow "NEPSE Notifier - server" $backend "& '$python' manage.py runserver"

# Hit rate, p-value and profit factor in admin > Quant come from these evaluations.
Step "Measuring any strategy not evaluated in the past week (admin > Quant strategies), in its own window"
StartWindow "NEPSE Notifier - strategy evaluation" $backend "& '$python' manage.py evaluate_strategies --stale-days 7"

if (Get-Command npm -ErrorAction SilentlyContinue) {
    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        Step "Installing dashboard packages"
        Push-Location $frontend
        try { Run npm install --no-fund --no-audit } finally { Pop-Location }
    }
    Step "Starting the dashboard at http://localhost:5173"
    StartWindow "NEPSE Notifier - dashboard" $frontend "npm run dev"
    if ($onWindows) {
        Start-Sleep -Seconds 5
        Start-Process "http://localhost:5173"
    }
} else {
    Write-Host "`nNode.js not found, so the dashboard was not started. Install the LTS version from https://nodejs.org and run this script again." -ForegroundColor Yellow
}

Write-Host "`nDone. Dashboard: http://localhost:5173   Admin: http://localhost:8000/admin" -ForegroundColor Green
Write-Host "Run this script again any time to fetch the latest prices." -ForegroundColor Green
