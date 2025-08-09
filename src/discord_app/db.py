from sqlalchemy import create_engine, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Discord user id
    auto_subscribe: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_instead: Mapped[bool] = mapped_column(Boolean, default=False)

class UserEvent(Base):
    __tablename__ = "user_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

def init_engine(db_path: str):
    # sqlite file; for in-memory tests, use sqlite://
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine

def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
