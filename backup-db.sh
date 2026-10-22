#!/bin/bash
# Ежедневный бэкап БД Fleet Manager. Запускается cron'ом в 23:00 по времени сервера
# (Asia/Yekaterinburg): backup-db.cron -> /etc/cron.d/fleet-manager-backup.
#
# Дампы: /opt/fleet-manager/_backup/daily/fleet_manager-ГГГГММДД-ЧЧММ.sql.gz (в git не
# попадают), хранятся KEEP_DAYS дней (по умолчанию 30), старые удаляются.
# В дампе хэши паролей и зашифрованные учётные данные — каталог и файлы только для root.
#
# Дамп считается удачным, только если архив целый и pg_dump дописал свою финальную
# строку «PostgreSQL database dump complete». Иначе файл не публикуется, а скрипт
# завершается с ошибкой — она видна в _logs/backup-db.log.
#
# Восстановление (пример — в отдельную БД, рабочая не трогается):
#   docker compose exec -T postgres createdb -U fleet fleet_restore
#   zcat _backup/daily/fleet_manager-<дата>.sql.gz | docker compose exec -T postgres psql -U fleet -d fleet_restore
set -euo pipefail

cd /opt/fleet-manager
DIR=/opt/fleet-manager/_backup/daily
KEEP_DAYS="${KEEP_DAYS:-30}"

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

OUT="$DIR/fleet_manager-$(date +%Y%m%d-%H%M).sql.gz"
# Итог последнего запуска для дашборда мониторинга (backend видит каталог только на чтение)
STATUS="$DIR/.last-run.json"
write_status() {  # $1 — ok|fail, $2 — сообщение, $3 — файл, $4 — размер в байтах
    local ok=false
    [ "$1" = ok ] && ok=true
    printf '{"finished_at":"%s","ok":%s,"message":"%s","file":"%s","size_bytes":%s,"keep_days":%s}\n' \
        "$(date --iso-8601=seconds)" "$ok" "$2" "${3:-}" "${4:-0}" "$KEEP_DAYS" > "$STATUS.tmp"
    mv "$STATUS.tmp" "$STATUS"
}
TMP="$OUT.part"
trap 'rm -f "$TMP"' EXIT
trap 'echo "$(date "+%F %T") FAIL: ошибка в строке $LINENO, бэкап не сделан"; write_status fail "ошибка в строке $LINENO, бэкап не сделан"' ERR

# Учётка и имя БД — из окружения контейнера postgres (.env); секретов в скрипте нет.
# </dev/null: иначе docker compose exec съедает stdin вызывающего скрипта.
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' </dev/null | gzip > "$TMP"
gzip -t "$TMP"
# С обновлений безопасности 2025 г. (PostgreSQL 15.14+/16.10+/17.6+) после строки
# «dump complete» pg_dump дописывает ещё пустую строку и «\unrestrict <ключ>» — смотрим хвост пошире
tail_lines=$(zcat "$TMP" | tail -n 10)
if [[ "$tail_lines" != *"PostgreSQL database dump complete"* ]]; then
    echo "$(date "+%F %T") FAIL: дамп оборван (нет финальной строки pg_dump), бэкап не сделан"
    write_status fail "дамп оборван (нет финальной строки pg_dump), бэкап не сделан"
    exit 1
fi
mv "$TMP" "$OUT"
trap - EXIT

find "$DIR" -maxdepth 1 -name 'fleet_manager-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
write_status ok "" "$(basename "$OUT")" "$(stat -c %s "$OUT")"
echo "$(date "+%F %T") OK $(basename "$OUT") $(du -h "$OUT" | cut -f1), копий: $(ls "$DIR"/fleet_manager-*.sql.gz | wc -l)"
