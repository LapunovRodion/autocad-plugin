#!/usr/bin/env bash
#
# Заливка исходных дампов в локальную Oracle XE.
#
# Дампы скармливаются sqlplus внутри контейнера через stdin — клиент Oracle
# на хосте не нужен, монтировать каталоги тоже не нужно.
#
# Скрипт идемпотентен: таблицы дропаются перед загрузкой, потому что сами
# дампы начинаются с CREATE TABLE и на повторном запуске упали бы.
#
# Использование:
#   ./infra/load-dumps.sh          залить и проверить
#   ./infra/load-dumps.sh --check  только контрольные запросы

set -euo pipefail

CONTAINER="${CONTAINER:-task-oracle}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# .env необязателен: значения по умолчанию совпадают с compose.yaml.
[[ -f "$ROOT/infra/.env" ]] && source "$ROOT/infra/.env"
APP_USER="${APP_USER:-TASK}"
APP_USER_PASSWORD="${APP_USER_PASSWORD:-task}"

if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  echo "Не найден ни podman, ни docker." >&2
  exit 1
fi

# sqlplus внутри контейнера. NLS_LANG обязателен: без него клиентская
# сторона перекодирует 'р112' и кириллица потеряется.
sqlplus_run() {
  "$ENGINE" exec -i \
    -e NLS_LANG=.AL32UTF8 \
    "$CONTAINER" \
    sqlplus -S -L "${APP_USER}/${APP_USER_PASSWORD}@localhost:1521/XEPDB1"
}

wait_for_db() {
  echo "Ожидание готовности базы..."
  for _ in $(seq 1 60); do
    if "$ENGINE" exec "$CONTAINER" healthcheck.sh >/dev/null 2>&1; then
      echo "База готова."
      return 0
    fi
    sleep 5
  done
  echo "База не поднялась за 5 минут. Логи: $ENGINE logs $CONTAINER" >&2
  exit 1
}

run_checks() {
  echo
  sqlplus_run < "$ROOT/infra/check.sql"
}

if ! "$ENGINE" inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Контейнер '$CONTAINER' не найден. Сначала:" >&2
  echo "  $ENGINE compose -f infra/compose.yaml up -d" >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  run_checks
  exit 0
fi

wait_for_db

# Порядок значения не имеет: внешних ключей между таблицами нет.
echo "Очистка предыдущей загрузки..."
sqlplus_run <<'SQL'
SET FEEDBACK OFF
-- Таблиц может не быть при первом запуске, поэтому ошибки подавляются.
BEGIN
  FOR t IN (SELECT table_name FROM user_tables
            WHERE table_name IN ('GEOMETRY', 'GPO', 'PROBA', 'PARAM')) LOOP
    EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' PURGE';
  END LOOP;
END;
/
EXIT
SQL

for dump in GPO PROBA PARAM GEOMETRY; do
  echo "Загрузка ${dump}.sql..."
  # WHENEVER SQLERROR прерывает загрузку на первой же ошибке, иначе sqlplus
  # молча проглотит её и таблица окажется залита частично.
  {
    echo "WHENEVER SQLERROR EXIT SQL.SQLCODE"
    echo "SET FEEDBACK OFF"
    cat "$ROOT/${dump}.sql"
    echo "EXIT"
  } | sqlplus_run
done

echo "Загрузка завершена."
run_checks
