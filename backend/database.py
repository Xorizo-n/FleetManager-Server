from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

# ВАЖНО: суммарный размер пула (pool_size + max_overflow) должен быть НЕ МЕНЬШЕ
# числа воркеров threadpool (см. main.py, DB_THREADPOOL_TOKENS=40). FastAPI
# выполняет sync-зависимости и хендлеры в threadpool отдельными задачами и держит
# соединение между ними; если воркеров threadpool больше, чем соединений в пуле,
# возникает кольцевой дедлок: соединения держат запросы, ждущие поток, а потоки
# ждут соединение (видно в pg_stat_activity как 20 «idle in transaction» + все
# потоки backend в pool checkout). 50 > 40 — дедлок исключён. PG max_connections=100,
# celery/beat используют свои пулы, суммарно остаёмся с запасом.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=30,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
