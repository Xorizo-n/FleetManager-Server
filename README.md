# FleetManager Server

Веб-система управления парком компьютеров с интеграцией Ansible: CMDB хостов, инвентаризация ПО, диагностика подключения, запуск плейбуков через Celery, Key Store для credentials, JWT+TOTP аутентификация, учёт и удалённое обновление версий агента.

## Связанные репозитории

- [FleetManager-Agent](https://github.com/Xorizo-n/FleetManager-Agent) — Windows-агент, который шлёт heartbeat и инвентаризацию на этот сервер.
- [RTF_OOD_AnsiblePlaybooks](https://github.com/kozlov174/RTF_OOD_AnsiblePlaybooks) — плейбуки установки ПО, которые сервер запускает через Ansible Runner.

## Структура

```
backend/    FastAPI + SQLAlchemy + Alembic + Celery
frontend/   React + TypeScript + Tailwind (Vite)
ansible/    плейбуки Fleet Manager, включая scan_software.yaml
```

## Запуск

```bash
cp .env.example .env
# сгенерировать секреты и вписать в .env:
openssl rand -hex 32                                                              # JWT_SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # CREDENTIAL_ENCRYPTION_KEY

docker compose build
docker compose up -d
```

- Frontend: http://localhost:8080
- Backend API + Swagger: http://localhost:8000/docs

Первый запуск: зарегистрируйте пользователя через `/auth/register` (первый зарегистрированный пользователь становится `admin`), затем привяжите TOTP на экране логина по QR-коду.

## Деплой на прод

Прод (`10.40.240.154`) — git-клон этого репозитория в `/opt/fleet-manager`, ветка `main`. Файлы на сервере не правятся: изменения идут через PR, а `git status` там должен оставаться чистым. `.env`, `_backup/` и `_logs/` в git не попадают.

```bash
cd /opt/fleet-manager
git pull --ff-only
docker compose build backend celery celery-beat frontend
docker compose up -d backend celery celery-beat frontend
docker builder prune -f
```

- Миграции применяются сами: backend при старте выполняет `alembic upgrade head`.
- PostgreSQL и Redis при этом не пересоздаются.
- Последняя команда обязательна: на сервере диск 15 ГБ, и кэш сборки (особенно когда заново собирается слой с `pip install`) заполняет его до конца.
- Перед `up -d` проверьте, что celery ничего не выполняет (`docker exec fleet-manager-celery-1 celery -A celery_app.celery_app inspect active`): пересоздание контейнера обрывает запущенные плейбуки.

## Группы хостов

Сервер сам раскладывает ПК по группам по имени, по той же схеме, что AutoDomain для OU: `КОРПУС-АУДИТОРИЯ-ТИП`, этаж — первая цифра номера аудитории.

`SU5-D206-TEMP` → `SU5` › `SU5 2 этаж` › `SU5-D206`

- ПК попадает в группу аудитории. Корпус и этаж — родительские группы; в inventory Ansible они вложены через `children`, на странице хостов показаны путём, а фильтр по корпусу или этажу включает все аудитории внутри.
- Группы создаются по мере появления ПК: при регистрации агента, при каждом heartbeat (переименованный ПК переходит в группу новой аудитории) и раз в час для всех хостов, включая добавленные вручную и выключенные.
- Существующая группа с именем аудитории (например, ручная `MR32-411`) не дублируется: она встраивается в дерево под своим этажом.
- ПК, которого администратор положил в ручную группу с другим именем, остаётся там. ПК с именами вне схемы (`DESKTOP-…`, `WIN10-VDI000`) не трогаются.
- Учётная запись группы наследуется вниз по дереву: учётка, заданная корпусу, действует для всех его аудиторий, если у хоста и его группы своей нет.
- Шаблон имени — `HOST_NAME_PATTERN` (регулярное выражение с группами `Building`, `Room`, `Floor`), отключить — `HOST_AUTO_GROUPING=false`.

## Версии агента

Установленная версия агента видна в реестре хостов (колонка «Агент») и на дашборде; доступная версия берётся из установщика, который сервер сам подтягивает из GitHub Releases. Кнопки «Проверить версии агента» и «Обновить агент» на странице хостов запускают проверку по SSH и удалённую установку свежего установщика поверх текущего — регистрация агента при этом сохраняется. Подробности API и механика обновления: [backend/README.md](backend/README.md).

## Переменные окружения

Смотрите `.env.example` — там описаны все обязательные секреты (JWT, Fernet-ключ для Key Store, параметры Postgres/Redis, CORS). `.env` в `.gitignore` — никогда не коммитьте реальные значения.

## Тесты

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # или source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
```

Тестам нужен заполненный `.env` в `backend/` (или переменные окружения) — `Settings` требует `jwt_secret_key` и `credential_encryption_key`; живая БД/Redis для этих тестов не нужны.

Фронтенд: `cd frontend && npm install && npm run build` (отдельного test-скрипта пока нет).
