from datetime import datetime, timezone
from sqlalchemy import create_engine, event, ForeignKey, UniqueConstraint, Index, String, Float, Integer, JSON, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import DATABASE_URL


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(default="ShanghaiT2DM v5")


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    profile: Mapped[dict] = mapped_column(JSON)
    source_sha256: Mapped[str]
    summary_sha256: Mapped[str]
    source_name: Mapped[str]
    start_time: Mapped[str]
    end_time: Mapped[str]
    count: Mapped[int]
    audit: Mapped[dict] = mapped_column(JSON)


class SourceReading(Base):
    """Archive only: model features must never query this table directly."""
    __tablename__ = "source_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), index=True)
    position: Mapped[int]
    time: Mapped[str]
    glucose: Mapped[float]
    __table_args__ = (UniqueConstraint("recording_id", "position"), UniqueConstraint("recording_id", "time"))


class ContextEvent(Base):
    """Immutable source cells; replay access is bounded by observed event time."""
    __tablename__ = "context_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"))
    source_key: Mapped[str]
    time: Mapped[str]
    kind: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("recording_id", "source_key"), Index("ix_context_recording_time", "recording_id", "time"))


class NutritionCatalog(Base):
    __tablename__ = "nutrition_catalogs"
    id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=utcnow)


class NutritionReference(Base):
    __tablename__ = "nutrition_references"
    id: Mapped[str] = mapped_column(primary_key=True)
    catalog_id: Mapped[str] = mapped_column(ForeignKey("nutrition_catalogs.id"), index=True)
    reference_key: Mapped[str]
    description: Mapped[str]
    nutrients: Mapped[dict] = mapped_column(JSON)
    portions: Mapped[list] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("catalog_id", "reference_key"),)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str]
    sha256: Mapped[str]
    info: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=utcnow)


class Replay(Base):
    __tablename__ = "replays"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"))
    model_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    cursor: Mapped[int] = mapped_column(default=0)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    virtual_time: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(default=utcnow)
    updated_at: Mapped[str] = mapped_column(default=utcnow)


class ObservedReading(Base):
    __tablename__ = "observed_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    replay_id: Mapped[str] = mapped_column(ForeignKey("replays.id"), index=True)
    time: Mapped[str]
    glucose: Mapped[float]
    received_at: Mapped[str] = mapped_column(default=utcnow)
    __table_args__ = (UniqueConstraint("replay_id", "time"),)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    replay_id: Mapped[str] = mapped_column(ForeignKey("replays.id"), index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    time: Mapped[str]
    due_at: Mapped[str]
    population_probability: Mapped[float]
    personal_probability: Mapped[float]
    features: Mapped[dict] = mapped_column(JSON)
    state_before: Mapped[dict] = mapped_column(JSON)
    state_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[int | None] = mapped_column(nullable=True)
    outcome_status: Mapped[str] = mapped_column(default="pending")
    updated_state: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=utcnow)
    __table_args__ = (UniqueConstraint("replay_id", "time"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), unique=True)
    replay_id: Mapped[str] = mapped_column(ForeignKey("replays.id"), index=True)
    time: Mapped[str]
    probability: Mapped[float]
    status: Mapped[str] = mapped_column(default="open")
    acknowledged_at: Mapped[str | None] = mapped_column(nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(index=True)
    entity_id: Mapped[str]
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(default=utcnow)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


def initialize():
    # The CLI uses Alembic; do not silently create/modify schema in the web process.
    from alembic.config import Config
    from alembic import command
    from .config import ROOT
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
