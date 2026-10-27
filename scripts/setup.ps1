# One-time setup for Windows (PowerShell). Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Requires: Python 3.10+ and PostgreSQL 14+ installed locally (or Docker Desktop).
param(
  [switch]$UseDocker,
  [string]$PostgresAdminUser = "postgres",
  [string]$PostgresAdminPassword = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

Step "Checking Python"
$py = $null
foreach ($c in @("py -3", "python", "python3")) {
  try { $v = & cmd /c "$c --version" 2>$null; if ($v -match "Python 3\.(\d+)") { if ([int]$Matches[1] -ge 10) { $py = $c; break } } } catch {}
}
if (-not $py) { throw "Python 3.10 or newer is required: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
Write-Host "Using $py ($v)"

Step "Creating virtual environment (.venv) and installing packages"
if (-not (Test-Path ".venv")) { cmd /c "$py -m venv .venv" }
$vpy = ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements-dev.txt --quiet

Step "Preparing the PostgreSQL database"
if ($UseDocker) {
  if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
  docker compose up -d db
  $content = Get-Content ".env" -Raw
  $content = $content -replace "(?m)^DATABASE_URL=.*$", "DATABASE_URL=postgres://cadet_user:change-me@localhost:5432/cadet_management"
  Set-Content ".env" $content -NoNewline
  Write-Host "Waiting for the database container..."
  Start-Sleep -Seconds 8
} else {
  if (-not $PostgresAdminPassword) {
    $sec = Read-Host "Password of the PostgreSQL '$PostgresAdminUser' user (set when you installed PostgreSQL)" -AsSecureString
    $PostgresAdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
  }
  & $vpy scripts\bootstrap_db.py --admin-user $PostgresAdminUser --admin-password $PostgresAdminPassword
  if ($LASTEXITCODE -ne 0) { throw "Database setup failed. Is PostgreSQL running? (Services -> postgresql-x64-NN)" }
}

Step "Applying migrations"
& $vpy manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "Migration failed." }

Step "Loading synthetic demo data"
& $vpy manage.py seed_demo --reset

Step "Running the automated tests"
& $vpy -m pytest -q

Write-Host "`nSetup complete. Start the app with:" -ForegroundColor Green
Write-Host "   .venv\Scripts\python manage.py runserver"
Write-Host "Then open http://127.0.0.1:8000  (sign in as admin@ocms.local / Cadet@Demo2026!)"
