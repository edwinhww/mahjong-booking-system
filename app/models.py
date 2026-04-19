import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class UserRole(str, enum.Enum):
    platform_owner = "platform_owner"
    business_owner = "business_owner"
    player = "player"


class UserStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"


class VenuePlayerStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    suspended = "suspended"


class TimeslotStatus(str, enum.Enum):
    open = "open"
    full = "full"
    closed = "closed"


class BookingStatus(str, enum.Enum):
    cooling_down = "cooling_down"
    locked = "locked"
    cancelled = "cancelled"


class MessageType(str, enum.Enum):
    reminder = "reminder"
    one_seat_left = "one_seat_left"
    table_full = "table_full"
    broadcast = "broadcast"


class MessageChannel(str, enum.Enum):
    in_app = "in_app"
    whatsapp_link = "whatsapp_link"


class AuditActionType(str, enum.Enum):
    table_confirmed = "table_confirmed"
    player_unlocked = "player_unlocked"
    player_approved = "player_approved"
    settings_changed = "settings_changed"


class ServiceCategory(str, enum.Enum):
    food = "food"
    drink = "drink"
    addon = "addon"


class CancellationRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "mahjoh_t_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.active, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Venue(Base):
    __tablename__ = "mahjoh_t_venues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    opening_time: Mapped[time] = mapped_column(Time, nullable=False)
    closing_time: Mapped[time] = mapped_column(Time, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    session_duration_hrs: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    session_fee: Mapped[float] = mapped_column(Numeric(10, 2), default=40, nullable=False)
    platform_fee_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=5, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)


class VenuePlayer(Base):
    __tablename__ = "mahjoh_t_venue_players"
    __table_args__ = (UniqueConstraint("venue_id", "player_id", name="uq_venue_player"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    status: Mapped[VenuePlayerStatus] = mapped_column(Enum(VenuePlayerStatus), default=VenuePlayerStatus.pending, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Timeslot(Base):
    __tablename__ = "mahjoh_t_timeslots"
    __table_args__ = (
        UniqueConstraint("venue_id", "date", "start_time", "table_number", name="uq_timeslot_venue_date_start_table"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    table_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TimeslotStatus] = mapped_column(Enum(TimeslotStatus), default=TimeslotStatus.open, nullable=False)


class Booking(Base):
    __tablename__ = "mahjoh_t_bookings"
    __table_args__ = (UniqueConstraint("timeslot_id", "player_id", name="uq_timeslot_player"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timeslot_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_timeslots.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.cooling_down, nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    cooldown_expires: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Message(Base):
    __tablename__ = "mahjoh_t_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    sent_by: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), nullable=False)
    content: Mapped[str] = mapped_column(String(600), nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    channel: Mapped[MessageChannel] = mapped_column(Enum(MessageChannel), default=MessageChannel.in_app, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "mahjoh_t_audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    action_type: Mapped[AuditActionType] = mapped_column(Enum(AuditActionType), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    session_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    platform_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    performed_by: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class VenueProfile(Base):
    __tablename__ = "mahjoh_t_venue_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), unique=True, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="GBP", nullable=False)
    business_whatsapp: Mapped[str] = mapped_column(String(30), nullable=False)
    business_whatsapp_cc: Mapped[str] = mapped_column(String(10), default="+852", nullable=False)
    business_whatsapp_local: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    nudge_window_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    nudge_message_template: Mapped[str] = mapped_column(Text, default="Hi {player_name}, we are filling a table around {slot_time}. Want to join today's game?", nullable=False)
    reminder_lead_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    reminder_message_template: Mapped[str] = mapped_column(Text, default="Hi {player_name}, this is a reminder that your Mahjong game starts at {slot_time} today.", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ServiceItem(Base):
    __tablename__ = "mahjoh_t_service_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    category: Mapped[ServiceCategory] = mapped_column(Enum(ServiceCategory), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BookingOrder(Base):
    __tablename__ = "mahjoh_t_booking_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    booking_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_bookings.id"), unique=True, nullable=False)
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    total_cost: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BookingOrderItem(Base):
    __tablename__ = "mahjoh_t_booking_order_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_booking_orders.id"), nullable=False)
    service_item_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_service_items.id"), nullable=False)
    service_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_cost_snapshot: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)


class BookingCancellationRequest(Base):
    __tablename__ = "mahjoh_t_booking_cancellation_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    booking_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_bookings.id"), nullable=False)
    venue_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=False)
    requested_by: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    status: Mapped[CancellationRequestStatus] = mapped_column(Enum(CancellationRequestStatus), default=CancellationRequestStatus.pending, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ActionAudit(Base):
    __tablename__ = "mahjoh_t_action_audit"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(ForeignKey("mahjoh_t_users.id"), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    venue_id: Mapped[str | None] = mapped_column(ForeignKey("mahjoh_t_venues.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
