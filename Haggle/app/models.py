"""Database tables (Appendix B of the Bible).

Tables are created with create_all, which is fine for development: after pulling a new version,
delete dalaal.db. Moving to real migrations (Alembic) is a post-hackathon job.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_name: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(8), default="hi")
    # {"onions": {"price": 30, "unit": "kg"}} -- what the owner usually pays (savings baseline)
    usual_prices: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Minutes the owner spends phoning suppliers for one typical order (from the interviews).
    manual_minutes_per_order: Mapped[float] = mapped_column(Float, default=15.0)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("owner_id", "key", name="uq_supplier_owner_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="hi")
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["onions", "oil"]
    on_time_count: Mapped[int] = mapped_column(Integer, default=0)
    late_count: Mapped[int] = mapped_column(Integer, default=0)
    no_answer_count: Mapped[int] = mapped_column(Integer, default=0)
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_days_usual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_usual: Mapped[bool] = mapped_column(Boolean, default=False)  # the owner's usual supplier
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    # [{"name": "onions", "quantity": 20, "unit": "kg"}, ...]
    items: Mapped[list] = mapped_column(JSON)
    deadline: Mapped[str] = mapped_column(String(8))  # "HH:MM", the owner's delivery deadline
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)

    baseline_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # {"onions": "ramesh", "oil": "ramesh"} for a single supplier, or two suppliers for a split
    assignments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    booked_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_saved_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_incurred: Mapped[float] = mapped_column(Float, default=0.0)

    ranking: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # latest ranking snapshot
    approval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    booking_attempts: Mapped[int] = mapped_column(Integer, default=0)
    excluded_suppliers: Mapped[list | None] = mapped_column(JSON, nullable=True)

    r1_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    r1_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Event(Base):
    """Append-only log. Every webhook and tool call is written here FIRST, untouched."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40))  # webhook | tool | system
    execution_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Our own reference, passed to the agent as a prompt variable so tool calls can name the call.
    call_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # Bolna's id. The unique constraint is what makes duplicate webhooks harmless.
    execution_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    supplier_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # supplier_r1 | supplier_r2 | approval | confirm | callback | intake
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="queued")
    status_rank: Mapped[int] = mapped_column(Integer, default=1)

    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answered_by_voicemail: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("call_id", "item", name="uq_quote_call_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), index=True)
    item: Mapped[str] = mapped_column(String(80))

    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # as spoken
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)     # as spoken, canonical
    base_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    price_per_base: Mapped[float | None] = mapped_column(Float, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mandi_flag: Mapped[str | None] = mapped_column(String(60), nullable=True)

    available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    delivery_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # True while the quote came only from the live submit_quote tool. The extraction at
    # `completed` confirms (and may correct) it.
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20), default="submit_quote")  # submit_quote | extraction

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
