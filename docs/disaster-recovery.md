# Восстановление Fleet Manager после потери ВМ

Копии вне ВМ делает `backend/services/offsite_backup.py` (настройка: Администрирование → «Резервные копии»). Они лежат в хранилище restic по SFTP и зашифрованы паролем шифрования копий.

## Что нужно иметь под рукой

- Адрес хранилища, логин и пароль SFTP: сейчас `backupuser@10.152.240.10`, каталог `/srv/backup/fleet-manager`.
- **Пароль шифрования копий.** Без него копии не открыть. В Fleet Manager он хранится в БД, которая пропала вместе с ВМ, поэтому его нужно хранить отдельно — в менеджере паролей или в сейфе.
- **IP-адрес 10.40.240.154.** Агенты обращаются к `http://10.40.240.154:8080`, а `sshd` на ПК принимает вход только с этого адреса. Новая ВМ должна получить тот же IP, иначе агентов придётся перенастраивать.

## Что в копиях

| Снимок (тег restic) | Когда | Содержимое |
|---|---|---|
| `db` | каждые 4 часа | `/fleet_manager.sql` — дамп БД (pg_dump, PostgreSQL 15) |
| `config` | вместе с `db` | `/mnt/fleet-config/.env` (ключ шифрования учётных данных, секреты), `/mnt/fleet-config/certs/`, `/app/ansible_data/local_playbooks/` |
| `share` | каждую ночь | `/mnt/soft-share` — установщики, обои, `FleetManagerAgent-Setup.exe` |

Хранение: `db`/`config` — все за 2 дня, затем 14 ежедневных, 8 недельных и 12 месячных; `share` — 7 ежедневных, 4 недельных и 6 месячных. По воскресеньям сервер сам восстанавливает последний дамп во временную БД и проверяет, что ключ из скопированного `.env` расшифровывает учётные данные. Итог виден на странице «Резервные копии» и на мониторинге.

## Восстановление на новой ВМ

1. Ubuntu 24.04, IP **10.40.240.154**, второй диск под `/mnt/soft-share`. Установить Docker с плагином compose, `git` и `restic`.
2. Клонировать репозиторий в `/opt/fleet-manager`, ветка `main`.
3. Подготовить доступ к хранилищу (вводить вручную, не сохранять в истории):

   ```bash
   export RESTIC_REPOSITORY='sftp:backupuser@10.152.240.10:/srv/backup/fleet-manager'
   read -rs RESTIC_PASSWORD && export RESTIC_PASSWORD   # пароль шифрования копий
   restic snapshots --host fleet-manager                 # restic спросит пароль SFTP
   ```

4. Вернуть конфигурацию и плейбуки:

   ```bash
   restic restore latest --tag config --host fleet-manager --target /tmp/fm-restore
   install -m 600 /tmp/fm-restore/mnt/fleet-config/.env /opt/fleet-manager/.env
   cp -a /tmp/fm-restore/mnt/fleet-config/certs /opt/fleet-manager/
   ```

5. Вернуть `/mnt/soft-share`: `restic restore latest --tag share --host fleet-manager --target /`. Это десятки гигабайт; запустить можно параллельно со следующими шагами.
6. Поднять только PostgreSQL и залить дамп:

   ```bash
   cd /opt/fleet-manager
   docker compose up -d postgres
   restic dump latest --tag db --host fleet-manager /fleet_manager.sql | docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

7. Поднять остальное: `docker compose up -d --build`. Миграции применятся при старте backend.
8. Локальные плейбуки вернуть в том `ansible_data`:

   ```bash
   docker compose cp /tmp/fm-restore/app/ansible_data/local_playbooks backend:/app/ansible_data/
   ```

9. Установить cron локального ежедневного дампа (`backup-db.cron`, см. README) и удалить `/tmp/fm-restore`: там `.env`.
10. Проверить работу:
    - через 5–10 минут на «Мониторинге» видно, что ПК шлют heartbeat;
    - «Хосты → Ещё → Проверить версии агента» проходит по SSH;
    - на «Резервных копиях» снова идут копии. Хранилище и пароли восстановились вместе с БД. Ключ SSH хранилища тоже уже закреплён в БД.

## Что теряется

- Всё, что изменилось после последнего снимка `db`, то есть не больше 4 часов. ПК, зарегистрированные за это время, сервер не узнает: агенты получат 401, и их нужно переустановить установщиком с токеном.
- Логи задач, которые выполнялись в момент сбоя.
