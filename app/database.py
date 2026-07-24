import os

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/quasar.db")

if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///./"):
    database_path = SQLALCHEMY_DATABASE_URL.removeprefix("sqlite:///./")
    database_dir = os.path.dirname(database_path)
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    """Make the demo SQLite store safer under concurrent API/background writes."""
    if not SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
