#!/usr/bin/env bash
# Кладёт ключ Meta (маркер системного пользователя) в .env офиса — запускает САМ владелец в Терминале.
# Ключ не печатается на экране и не попадает в историю команд. Агент этот скрипт не запускает.
#   bash scripts/targetolog-klyuch.sh            → переменная META_TOKEN
#   bash scripts/targetolog-klyuch.sh META_TOKEN_2 → другое имя (второй кабинет)
set -euo pipefail
cd "$(dirname "$0")/.."
VAR="${1:-META_TOKEN}"
case "$VAR" in *[!A-Z0-9_]*|"") echo "Имя переменной — только A-Z, 0-9, _"; exit 1;; esac

echo "Вставь ключ Meta (символы не видны — так и должно быть) и нажми Enter:"
IFS= read -rs KEY
echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
if [ ${#KEY} -lt 50 ]; then
  echo "⛔ Ключ слишком короткий (${#KEY} символов). Скопируй его целиком из окна «Сгенерировать маркер»."
  exit 1
fi

touch .env
chmod 600 .env
if grep -q "^${VAR}=" .env; then
  # заменить старое значение, не трогая остальные строки
  tmp="$(mktemp)"
  grep -v "^${VAR}=" .env > "$tmp" || true
  cat "$tmp" > .env
  rm -f "$tmp"
  echo "Старый ${VAR} заменён."
fi
printf '%s=%s\n' "$VAR" "$KEY" >> .env
unset KEY

if [ -f .gitignore ] && ! grep -qx ".env" .gitignore; then
  echo ".env" >> .gitignore
fi
echo "✅ Ключ сохранён в .env как ${VAR}. Вернись в чат с Клодом и напиши: «положил ключ»."
