from datetime import date, datetime, time
from pydantic import BaseModel, Field

from .models import BookingStatus, CancellationRequestStatus, MessageChannel, MessageType, ServiceCategory, UserRole, UserStatus, VenuePlayerStatus


class HealthResponse(BaseModel):
    status: str


class UserCreate(BaseModel):
    name: str
    phone: str
    email: str | None = None
    password: str = Field(min_length=4)
    role: UserRole


class LoginRequest(BaseModel):
    phone: str
    password: str


class UserRead(BaseModel):
    id: str
    name: str
    phone: str
    role: UserRole
    status: UserStatus
    must_change_password: bool = False


class AuthResponse(BaseModel):
    token: str
    user: UserRead


class VenueCreate(BaseModel):
    owner_id: str
    name: str
    opening_time: time
    closing_time: time
    table_count: int = Field(ge=1, le=20, default=4)
    session_duration_hrs: int = Field(ge=1, le=6, default=2)
    cooldown_minutes: int = Field(ge=5, le=120, default=30)
    session_fee: float = Field(gt=0, default=40)
    platform_fee_pct: float = Field(ge=0, le=100, default=5)


class VenueRead(VenueCreate):
    id: str
    status: str


class VenueUpdate(BaseModel):
    name: str | None = None
    opening_time: time | None = None
    closing_time: time | None = None
    table_count: int | None = Field(default=None, ge=1, le=20)
    session_duration_hrs: int | None = Field(default=None, ge=1, le=6)
    cooldown_minutes: int | None = Field(default=None, ge=5, le=120)
    session_fee: float | None = Field(default=None, gt=0)
    platform_fee_pct: float | None = Field(default=None, ge=0, le=100)


class VenueUpdateResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    opening_time: time
    closing_time: time
    table_count: int
    session_duration_hrs: int
    cooldown_minutes: int
    session_fee: float
    platform_fee_pct: float
    status: str
    reallocated_count: int = 0
    draft_count: int = 0


class VenueBookingRead(BaseModel):
    id: str
    timeslot_id: str
    player_id: str
    status: BookingStatus
    booked_at: datetime
    cooldown_expires: datetime
    table_number: int
    start_time: time
    end_time: time


class VenuePlayerDetailRead(BaseModel):
    id: str
    player_id: str
    player_name: str
    player_phone: str
    status: VenuePlayerStatus
    created_at: datetime


class VenueJoinRequest(BaseModel):
    player_id: str


class VenuePlayerRead(BaseModel):
    id: str
    venue_id: str
    player_id: str
    status: VenuePlayerStatus
    created_at: datetime


class TimeslotRead(BaseModel):
    id: str
    venue_id: str
    date: date
    start_time: time
    end_time: time
    table_number: int
    status: str


class BookingCreate(BaseModel):
    player_id: str


class BookingRead(BaseModel):
    id: str
    timeslot_id: str
    player_id: str
    status: BookingStatus
    booked_at: datetime
    cooldown_expires: datetime


class MessageCreate(BaseModel):
    sent_by: str
    message_type: MessageType
    content: str
    recipient_count: int = Field(ge=1, default=1)
    channel: MessageChannel = MessageChannel.in_app


class MessageRead(BaseModel):
    id: str
    venue_id: str
    sent_by: str
    message_type: MessageType
    content: str
    recipient_count: int
    channel: MessageChannel
    sent_at: datetime


class AuditRead(BaseModel):
    id: str
    venue_id: str
    action_type: str
    reference_id: str | None
    session_fee: float | None
    platform_fee: float | None
    performed_by: str
    created_at: datetime


class VenueProfileUpsert(BaseModel):
    currency_code: str = Field(min_length=3, max_length=3)
    business_whatsapp: str
    business_whatsapp_cc: str = Field(default="+852", max_length=10)
    business_whatsapp_local: str = Field(default="", max_length=20)
    nudge_window_minutes: int = Field(default=60, ge=0, le=240)
    nudge_message_template: str = Field(default="Hi {player_name}, we are filling a table around {slot_time}. Want to join today's game?", min_length=1, max_length=600)
    reminder_lead_minutes: int = Field(default=30, ge=0, le=240)
    reminder_message_template: str = Field(default="Hi {player_name}, this is a reminder that your Mahjong game starts at {slot_time} today.", min_length=1, max_length=600)


class VenueProfileRead(BaseModel):
    id: str
    venue_id: str
    currency_code: str
    business_whatsapp: str
    business_whatsapp_cc: str
    business_whatsapp_local: str
    nudge_window_minutes: int
    nudge_message_template: str
    reminder_lead_minutes: int
    reminder_message_template: str
    updated_at: datetime


class ServiceItemCreate(BaseModel):
    category: ServiceCategory
    name: str
    description: str = ""
    image_url: str | None = None
    cost: float = Field(gt=0)
    is_active: bool = True


class ServiceItemUpdate(BaseModel):
    category: ServiceCategory | None = None
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    cost: float | None = Field(default=None, gt=0)
    is_active: bool | None = None


class ServiceItemRead(BaseModel):
    id: str
    venue_id: str
    category: ServiceCategory
    name: str
    description: str
    image_url: str | None
    cost: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrderItemInput(BaseModel):
    service_item_id: str
    quantity: int = Field(ge=1, le=50)


class BookingWithOrderCreate(BaseModel):
    player_id: str
    order_items: list[OrderItemInput] = Field(default_factory=list)


class BookingOrderItemRead(BaseModel):
    id: str
    service_item_id: str
    service_name_snapshot: str
    unit_cost_snapshot: float
    quantity: int
    line_total: float


class BookingOrderRead(BaseModel):
    id: str
    booking_id: str
    venue_id: str
    player_id: str
    total_cost: float
    created_at: datetime
    updated_at: datetime
    items: list[BookingOrderItemRead] = Field(default_factory=list)


class BookingAndOrderRead(BaseModel):
    booking: BookingRead
    order: BookingOrderRead


class CancellationRequestCreate(BaseModel):
    actor_id: str
    reason: str | None = None


class CancellationRequestReview(BaseModel):
    reviewer_id: str
    approve: bool


class CancellationRequestRead(BaseModel):
    id: str
    booking_id: str
    venue_id: str
    requested_by: str
    status: CancellationRequestStatus
    reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


class OrderHistoryRow(BaseModel):
    order_id: str
    booking_id: str
    player_id: str
    player_name: str
    player_phone: str
    total_cost: float
    booking_status: BookingStatus
    booking_time: datetime
    created_at: datetime
    items_summary: str


class UserAdminUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    status: UserStatus | None = None


class PlayerVenueStatsRead(BaseModel):
    player_id: str
    joined_at: datetime | None
    last_game_played_at: datetime | None
    total_games_played: int
    total_hours_played: float
    total_spending: float


class ActionAuditRead(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    venue_id: str | None
    action_type: str
    target_type: str | None
    target_id: str | None
    metadata_json: str | None
    created_at: datetime
