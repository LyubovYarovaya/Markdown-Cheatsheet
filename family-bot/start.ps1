# Запуск на Windows одной командой:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
# Делает venv, ставит зависимости, спрашивает токен, поднимает https-туннель
# и подставляет его адрес в .env.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Ok    ($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Warn  ($m) { Write-Host "!   $m" -ForegroundColor Yellow }
function Fail  ($m) { Write-Host "X   $m" -ForegroundColor Red; exit 1 }

# --- 1. Python ------------------------------------------------------------------

$python = $null
foreach ($candidate in @('py -3.12', 'py -3.11', 'py -3', 'python')) {
    $parts = $candidate.Split(' ')
    if (Get-Command $parts[0] -ErrorAction SilentlyContinue) {
        $check = & $parts[0] $parts[1..($parts.Length - 1)] -c 'import sys; print(sys.version_info >= (3, 11))' 2>$null
        if ($check -eq 'True') { $python = $candidate; break }
    }
}
if (-not $python) { Fail 'Нужен Python 3.11+. Поставь с python.org/downloads и отметь галочку "Add Python to PATH"' }
Ok "Python: $python"

$pyParts = $python.Split(' ')
function Invoke-Py { & $pyParts[0] $pyParts[1..($pyParts.Length - 1)] @args }

function Set-EnvValue([string]$key, [string]$value) {
    $lines = Get-Content .env -Encoding UTF8
    $done = $false
    $lines = $lines | ForEach-Object {
        if ($_.Split('=')[0].Trim() -eq $key) { $done = $true; "$key=$value" } else { $_ }
    }
    if (-not $done) { $lines += "$key=$value" }
    Set-Content .env -Value $lines -Encoding UTF8
}

function Get-EnvValue([string]$key) {
    if (-not (Test-Path .env)) { return '' }
    foreach ($line in Get-Content .env -Encoding UTF8) {
        if ($line.Split('=')[0].Trim() -eq $key -and $line.Contains('=')) {
            return $line.Substring($line.IndexOf('=') + 1).Trim()
        }
    }
    return ''
}

# --- 2. Виртуальное окружение и зависимости -------------------------------------

if (-not (Test-Path .venv)) {
    Write-Host 'Создаю виртуальное окружение...' -ForegroundColor DarkGray
    Invoke-Py -m venv .venv
}
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { Fail 'Не нашла python внутри .venv — удали папку .venv и запусти скрипт заново' }

$stamp = '.venv\.deps-installed'
if (-not (Test-Path $stamp) -or (Get-Item requirements.txt).LastWriteTime -gt (Get-Item $stamp).LastWriteTime) {
    Write-Host 'Ставлю зависимости (первый раз это пара минут)...' -ForegroundColor DarkGray
    & $venvPy -m pip install --quiet --upgrade pip
    & $venvPy -m pip install --quiet -r requirements.txt
    New-Item -ItemType File -Path $stamp -Force | Out-Null
}
Ok 'Зависимости на месте'

# --- 3. Настройки и токен бота --------------------------------------------------

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$token = Get-EnvValue 'BOT_TOKEN'
if ([string]::IsNullOrWhiteSpace($token) -or $token.StartsWith('123456:ABC-DEF')) {
    Write-Host ''
    Write-Host 'Нужен токен бота. Открой @BotFather в Telegram -> /newbot -> скопируй строку вида 8123456789:AAF...'
    $token = Read-Host 'Вставь токен'
    if ([string]::IsNullOrWhiteSpace($token)) { Fail 'Без токена бот не запустится' }
    Set-EnvValue 'BOT_TOKEN' $token
}
Ok 'Токен бота записан в .env'

$port = Get-EnvValue 'PORT'
if ([string]::IsNullOrWhiteSpace($port)) { $port = '8080' }

# --- 4. HTTPS-туннель для мини-приложения ---------------------------------------

$tunnel = $null
try {
    if ($env:SKIP_TUNNEL -eq '1') {
        Warn 'Туннель пропущен (SKIP_TUNNEL=1) — мини-приложение и ссылки для гостей работать не будут'
    }
    elseif (Get-Command cloudflared -ErrorAction SilentlyContinue) {
        $log = Join-Path $env:TEMP 'cloudflared.log'
        Remove-Item $log -ErrorAction SilentlyContinue
        $tunnel = Start-Process cloudflared `
            -ArgumentList 'tunnel', '--url', "http://localhost:$port", '--no-autoupdate' `
            -RedirectStandardError $log -RedirectStandardOutput "$log.out" -PassThru -WindowStyle Hidden

        Write-Host 'Поднимаю https-туннель...' -ForegroundColor DarkGray
        $url = ''
        foreach ($i in 1..40) {
            Start-Sleep -Seconds 1
            if (Test-Path $log) {
                $match = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
                if ($match) { $url = $match.Matches[0].Value; break }
            }
        }
        if ($url) {
            Set-EnvValue 'PUBLIC_URL' $url
            Ok "Публичный адрес: $url"
            Warn 'Этот адрес живёт только пока скрипт запущен. После перезапуска он сменится,'
            Warn 'и ссылки на вишлисты, которые ты уже раздала, перестанут открываться.'
        } else {
            Warn "Туннель не поднялся — смотри $log. Бот заработает, мини-приложение — нет."
        }
    }
    else {
        Warn 'cloudflared не установлен — бот будет работать, мини-приложение и ссылки для гостей нет.'
        Warn 'Скачать: github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.exe)'
    }

    # --- 5. Поехали -------------------------------------------------------------

    Write-Host ''
    Ok 'Запускаю. Открой бота в Telegram и нажми /start'
    Write-Host 'Остановить — Ctrl+C' -ForegroundColor DarkGray
    Write-Host ''
    & $venvPy -m app.main
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
}
