# Mahjong Booking System - Architecture Discussion Draft

## 1. Agreed Product Scope

This document reflects the requirements already confirmed:

- Game requires exactly 4 players per table session.
- Mobile web first, runs on iPhone and Android browsers.
- Role hierarchy: platform owner > business owner > player.
- Multi-venue from day one.
- Player registration can be initiated by player or admin.
- Player must be approved by venue business owner before booking.
- Venue is created by platform owner (not self-onboarding in phase 1).
- Booking has a 30-minute undo cooldown.
- After cooldown, player is locked and only business owner can unlock.
- System tracks full-table sessions for audit and platform fee calculation.
- Hosting target: Heroku.
- Messaging preference:
  - Phase 1: in-app messaging + click-to-chat WhatsApp links.
  - Phase 2: outbound automated WhatsApp API.
- Payments are desired, but targeted for phase 2.

## 2. Core Personas and Permissions

### Platform owner

- Creates and manages venues.
- Assigns business owner account to each venue.
- Sets global defaults and platform fee strategy.
- Views cross-venue audit and billing summary.

### Business owner (per venue)

- Approves or suspends players for own venue.
- Sets opening hours, table count, session duration, cooldown.
- Manages schedule and unlocks bookings after lock.
- Sends messages/reminders to venue player list.
- Views venue-level audit and exports CSV.

### Player (per venue membership)

- Registers and requests access to venue.
- Views available timeslots for approved venues.
- Books one seat per timeslot.
- Can undo booking during cooldown window.
- Receives notifications when table reaches 4 players.

## 3. Functional Flow (Happy Path)

1. Platform owner creates venue and business owner account.
2. Player self-registers and requests venue access.
3. Business owner approves player.
4. Player books a seat in a timeslot.
5. Booking enters cooling_down state with expiry timestamp.
6. Additional players join until seat count reaches 4.
7. System marks table as full and sends notification event.
8. When cooldown expires, booking becomes locked.
9. If all 4 seats are locked, create billable audit event.

## 4. Booking State Model

Suggested booking state machine:

- pending_approval (venue membership level, not booking)
- cooling_down
- confirmed_full (timeslot-level event when 4 seats reached)
- locked
- cancelled_by_player (within cooldown)
- unlocked_by_admin (post-lock release)

Rules:

- Undo allowed only while now < cooldown_expires.
- After lock, only business owner unlock endpoint can release seat.
- Audit billable event should be generated once per full table per session.

## 5. Data Model (Multi-Venue)

## users

- id (uuid, pk)
- name
- phone (unique)
- email (nullable)
- password_hash
- role (platform_owner, business_owner, player)
- status (pending, active, suspended)
- created_at

## venues

- id (uuid, pk)
- owner_id (fk users.id)
- name
- opening_time
- closing_time
- table_count
- session_duration_hrs
- cooldown_minutes
- session_fee
- platform_fee_pct
- status

## venue_players

- id (uuid, pk)
- venue_id (fk venues.id)
- player_id (fk users.id)
- status (pending, approved, suspended)
- approved_by (fk users.id, nullable)
- approved_at (nullable)
- created_at

## timeslots

- id (uuid, pk)
- venue_id (fk venues.id)
- date
- start_time
- end_time
- table_number
- status (open, full, closed)

## bookings

- id (uuid, pk)
- timeslot_id (fk timeslots.id)
- player_id (fk users.id)
- status
- booked_at
- cooldown_expires
- locked_at (nullable)
- cancelled_by (fk users.id, nullable)
- cancelled_at (nullable)

## messages

- id (uuid, pk)
- venue_id (fk venues.id)
- sent_by (fk users.id)
- message_type (reminder, nudge, table_full, one_seat_left, custom)
- channel (in_app, whatsapp_link, whatsapp_api)
- content
- recipient_count
- sent_at

## audit_log

- id (uuid, pk)
- venue_id (fk venues.id)
- action_type (table_confirmed, player_unlocked, player_approved, settings_changed)
- reference_id (nullable)
- session_fee
- platform_fee
- performed_by (fk users.id)
- created_at

## 6. API Surface (Phase 1)

### Auth

- POST /auth/register
- POST /auth/login
- POST /auth/logout
- POST /auth/change-password

### Platform owner

- POST /platform/venues
- GET /platform/venues
- PATCH /platform/venues/{venue_id}
- GET /platform/audit

### Business owner

- GET /venues/{venue_id}/players
- PATCH /venues/{venue_id}/players/{player_id}/approve
- PATCH /venues/{venue_id}/players/{player_id}/suspend
- GET /venues/{venue_id}/timeslots
- PATCH /venues/{venue_id}/settings
- PATCH /bookings/{booking_id}/unlock
- POST /venues/{venue_id}/messages
- GET /venues/{venue_id}/audit

### Player

- POST /venues/{venue_id}/join
- GET /venues/{venue_id}/timeslots
- POST /timeslots/{timeslot_id}/book
- DELETE /bookings/{booking_id}
- GET /me/bookings
- POST /venues/{venue_id}/contact

## 7. Messaging Strategy

## Phase 1 (low setup, low cost)

- In-app notifications for state changes.
- WhatsApp click-to-chat link for direct user/admin contact.
- Business owner can trigger prefilled reminder links.

## Phase 2 (automated outbound)

- Integrate WhatsApp Business API provider.
- Template-based sends for table full, one seat left, reminder.
- Delivery status and retries logged in messages table.

## 8. Payments and Cost Impact (Phase 2)

Additional work required:

- Payment intent and checkout API.
- Webhook processing and idempotency handling.
- Payment/refund tables and reconciliation UI.
- Venue settlement and platform fee split logic.
- Basic dispute/refund handling workflow.

Estimated engineering impact:

- Around 3 to 4 weeks for first production-ready version.

Recurring cost considerations:

- Payment provider processing fees per transaction.
- Optional provider costs for marketplace split payouts.

## 9. Deployment Architecture on Heroku

- Frontend: static build served via CDN or app web dyno.
- Backend API: FastAPI app on Heroku web dyno.
- Database: Heroku Postgres.
- Scheduler: Heroku Scheduler for cooldown-lock job.
- Cache/queue (optional): Redis for rate-limits and job queue in later phase.

## 10. Mobile Web/PWA Readiness

- Responsive, touch-first layout.
- Add to Home Screen support.
- Offline fallback for static shell.
- Push notifications optional in phase 2.

## 11. Security Baseline

- Password hashing (Argon2 or bcrypt).
- JWT with refresh token rotation.
- Role-based access checks at endpoint and query layer.
- Audit trail for all admin unlock and settings changes.
- Rate limiting for login and messaging endpoints.

## 12. Recommended Build Plan

Phase 1a (foundation)

- Auth, roles, venues, approval workflow, timeslot generation.

Phase 1b (booking engine)

- Booking, cooldown, lock job, unlock by admin.

Phase 1c (operations)

- Messaging panel, audit dashboard, CSV export, Heroku deployment.

Phase 2

- WhatsApp API automation and Stripe payments.

## 13. Open Decisions (for final spec)

- One player allowed in multiple simultaneous venue memberships? (recommended yes)
- Maximum concurrent bookings per player per day? (recommended configurable)
- Timeslot overlap rules across tables at same venue? (recommended strict by table)
- Cancellation policy after lock (admin notes + reason code)?
