from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

# Connection pool sized for 15+ concurrent users.
# Each gunicorn worker has its own pool, so total connections =
#   (pool_size + max_overflow) * worker_count
# With 4 workers: (20 + 30) * 4 = 200 potential connections.
# If Postgres max_connections is 100, drop workers to 2 or
# reduce pool_size. Tune together with worker count.
engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for FastAPI to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables from models (dev only — use Alembic in prod)."""
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("Database initialized with all tables")
