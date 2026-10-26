FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        sshpass \
        build-essential \
        nsis \
        restic \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# pg_dump/psql той же версии, что и сервер БД (postgres:15): клиент 17 из trixie пишет в дамп
# SET transaction_timeout, которого PostgreSQL 15 не знает (services/offsite_backup.py)
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-15 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/usr/lib/postgresql/15/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ansible-collections.yml /tmp/ansible-collections.yml
RUN ansible-galaxy collection install -r /tmp/ansible-collections.yml

COPY . .

# fm_fetch: плейбуки качают установщики с точки раздачи (services/distribution.py)
ENV ANSIBLE_ACTION_PLUGINS=/app/ansible_plugins/action

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
