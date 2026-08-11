# FleetManager Server

Веб-система управления парком компьютеров с интеграцией Ansible: CMDB хостов, инвентаризация ПО, диагностика подключения, запуск плейбуков через Celery, Key Store для credentials, JWT+TOTP аутентификация.

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
