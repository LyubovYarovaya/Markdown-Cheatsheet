#!/usr/bin/env bash
# Запуск на своей машине одной командой: ./start.sh
# Делает venv, ставит зависимости, спрашивает токен, поднимает https-туннель
# и подставляет его адрес в .env — руками копировать ничего не нужно.
set -euo pipefail
cd "$(dirname "$0")"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

# --- 1. Python ------------------------------------------------------------------

PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || die "Нужен Python 3.11+. macOS: brew install python@3.12 · Windows: python.org/downloads · Linux: sudo apt install python3 python3-venv"
ok "Python: $("$PY" --version)"

# Небольшой помощник: правит ключ в .env одинаково на macOS и Linux (sed везде разный).
set_env() {
  "$PY" - "$1" "$2" <<'PYCODE'
import pathlib, sys
key, value = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if line.split("=", 1)[0].strip() == key:
        lines[index] = f"{key}={value}"
        break
else:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PYCODE
}

get_env() {
  "$PY" - "$1" <<'PYCODE'
import pathlib, sys
key = sys.argv[1]
path = pathlib.Path(".env")
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.split("=", 1)[0].strip() == key and "=" in line:
            print(line.split("=", 1)[1].strip())
            break
PYCODE
}

# --- 2. Виртуальное окружение и зависимости -------------------------------------

if [ ! -d .venv ]; then
  say "${DIM}Создаю виртуальное окружение…${OFF}"
  "$PY" -m venv .venv
fi
VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY=".venv/Scripts/python.exe"   # git-bash на Windows
[ -x "$VENV_PY" ] || die "Не нашла python внутри .venv — удали папку .venv и запусти скрипт заново"

STAMP=".venv/.deps-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  say "${DIM}Ставлю зависимости (первый раз это пара минут)…${OFF}"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi
ok "Зависимости на месте"

# --- 3. Настройки и токен бота --------------------------------------------------

[ -f .env ] || cp .env.example .env

TOKEN="$(get_env BOT_TOKEN)"
case "$TOKEN" in
  ""|123456:ABC-DEF*)
    say ""
    say "Нужен токен бота. Открой @BotFather в Telegram → /newbot → скопируй строку вида 8123456789:AAF…"
    printf 'Вставь токен: '
    read -r TOKEN
    [ -n "$TOKEN" ] || die "Без токена бот не запустится"
    set_env BOT_TOKEN "$TOKEN"
    ;;
esac
ok "Токен бота записан в .env"

PORT="$(get_env PORT)"; PORT="${PORT:-8080}"

# --- 4. HTTPS-туннель для мини-приложения ---------------------------------------

TUNNEL_PID=""
cleanup() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${SKIP_TUNNEL:-}" = "1" ]; then
  warn "Туннель пропущен (SKIP_TUNNEL=1) — мини-приложение и ссылки для гостей работать не будут"
elif command -v cloudflared >/dev/null 2>&1; then
  LOG="$(mktemp)"
  cloudflared tunnel --url "http://localhost:${PORT}" --no-autoupdate >"$LOG" 2>&1 &
  TUNNEL_PID=$!
  printf '%s' "${DIM}Поднимаю https-туннель"
  URL=""
  for _ in $(seq 1 40); do
    URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -1 || true)"
    [ -n "$URL" ] && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || break
    printf '.'
    sleep 1
  done
  printf '%s\n' "$OFF"

  if [ -n "$URL" ]; then
    set_env PUBLIC_URL "$URL"
    ok "Публичный адрес: $URL"
    warn "Этот адрес живёт только пока скрипт запущен. После перезапуска он сменится,"
    warn "и ссылки на вишлисты, которые ты уже раздала, перестанут открываться."
  else
    warn "Туннель не поднялся — смотри $LOG. Бот заработает, мини-приложение — нет."
  fi
else
  warn "cloudflared не установлен — бот будет работать, мини-приложение и ссылки для гостей нет."
  warn "Поставить: macOS — brew install cloudflared · Linux — из релизов github.com/cloudflare/cloudflared"
fi

# --- 5. Поехали -----------------------------------------------------------------

say ""
ok "Запускаю. Открой бота в Telegram и нажми /start"
say "${DIM}Остановить — Ctrl+C${OFF}"
say ""
exec "$VENV_PY" -m app.main
