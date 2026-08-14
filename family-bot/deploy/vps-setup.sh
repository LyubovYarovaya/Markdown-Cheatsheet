#!/usr/bin/env bash
# Разворачивает бота на чистом сервере (Ubuntu/Debian) так, чтобы он работал
# всегда — без включённого ноутбука, с постоянным адресом и https.
#
#   git clone -b claude/telegram-shopping-expenses-bot-7rboan <репозиторий>
#   cd Markdown-Cheatsheet/family-bot
#   sudo ./deploy/vps-setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запусти через sudo: sudo ./deploy/vps-setup.sh"

# --- Docker ---------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
  printf '%sСтавлю Docker…%s\n' "$DIM" "$OFF"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "Нужен docker compose (плагин v2)"
ok "Docker готов"

# --- Домен и токен --------------------------------------------------------------

[ -f .env ] || cp .env.example .env

read_value() {  # ключ -> значение из .env
  python3 - "$1" <<'PYCODE'
import pathlib, sys
key = sys.argv[1]
path = pathlib.Path(".env")
for line in path.read_text(encoding="utf-8").splitlines():
    if line.split("=", 1)[0].strip() == key and "=" in line:
        print(line.split("=", 1)[1].strip())
        break
PYCODE
}

write_value() {
  python3 - "$1" "$2" <<'PYCODE'
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

DOMAIN="$(read_value DOMAIN)"
if [ -z "$DOMAIN" ]; then
  echo ""
  echo "Домен, который смотрит A-записью на этот сервер."
  echo "Бесплатно можно взять на duckdns.org — например, family-borets.duckdns.org"
  printf 'Домен: '
  read -r DOMAIN
  [ -n "$DOMAIN" ] || die "Без домена не будет https, а без https Telegram не откроет приложение"
  write_value DOMAIN "$DOMAIN"
fi

TOKEN="$(read_value BOT_TOKEN)"
case "$TOKEN" in
  ""|123456:ABC-DEF*)
    printf 'Токен бота от @BotFather: '
    read -r TOKEN
    [ -n "$TOKEN" ] || die "Без токена бот не запустится"
    write_value BOT_TOKEN "$TOKEN"
    ;;
esac

write_value PUBLIC_URL "https://${DOMAIN}"
write_value BOT_MODE polling
ok "Настройки записаны в .env"

# Проверяем, что домен действительно ведёт сюда — иначе Let's Encrypt не выдаст
# сертификат, и понять это по логам Caddy сложнее, чем сейчас.
SERVER_IP="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
DOMAIN_IP="$(getent hosts "$DOMAIN" | awk '{print $1; exit}' || true)"
if [ -n "$SERVER_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
  warn "Домен $DOMAIN ведёт на $DOMAIN_IP, а сервер — $SERVER_IP."
  warn "Поправь A-запись, иначе сертификат не выпустится."
elif [ -z "$DOMAIN_IP" ]; then
  warn "Домен $DOMAIN пока не резолвится — DNS может обновляться до нескольких минут."
fi

# --- Запуск ---------------------------------------------------------------------

export DOMAIN
docker compose -f deploy/docker-compose.prod.yml up -d --build
ok "Контейнеры подняты"

echo ""
echo "Проверить: docker compose -f deploy/docker-compose.prod.yml logs -f app"
echo "Адрес приложения: https://${DOMAIN}/app/"
echo ""
ok "Готово. Открой бота в Telegram и нажми /start"
