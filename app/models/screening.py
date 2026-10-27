"""SQLAlchemy model: one row per screening DECISION, unique by payment reference.
It holds decisions only: no names, phone numbers or wallets."""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ScreeningRecord(Base):
    __tablename__ = "screening_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # UNIQUE: even across processes the database refuses a second row for the same reference.
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    recommended_action: Mapped[str] = mapped_column(String(16))
    screening_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
