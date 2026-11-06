"""Core classes for an in-memory event ticketing prototype.

Prices are stored as integer paise to avoid floating-point currency errors.
This module contains the core data classes and an in-memory booking workflow.
It does not include an API or persistent database.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from threading import Lock
from uuid import uuid4


class TicketType:
    """A ticket category for an event, such as Silver or Gold."""

    def __init__(self, name: str, capacity: int, base_price_paise: int) -> None:
        if capacity <= 0:
            raise ValueError("Ticket capacity must be greater than zero.")
        if base_price_paise < 0:
            raise ValueError("Ticket price cannot be negative.")

        self.name = name
        self.capacity = capacity
        self.base_price_paise = base_price_paise
        self.tickets_sold = 0

    def available_quantity(self) -> int:
        """Return the number of tickets that can still be booked."""
        return self.capacity - self.tickets_sold

    def record_sale(self, quantity: int) -> None:
        """Add tickets to the sold count after a successful payment."""
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if quantity > self.available_quantity():
            raise ValueError("Not enough tickets are available.")

        self.tickets_sold += quantity

    def return_tickets(self, quantity: int) -> None:
        """Return cancelled tickets to inventory."""
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if quantity > self.tickets_sold:
            raise ValueError("Cannot return more tickets than have been sold.")

        self.tickets_sold -= quantity


class Event:
    """An event and the ticket categories available for it."""

    def __init__(
        self,
        event_id: str,
        name: str,
        event_date: date,
        description: str = "",
    ) -> None:
        self.event_id = event_id
        self.name = name
        self.event_date = event_date
        self.description = description
        self.ticket_types: dict[str, TicketType] = {}

    def add_ticket_type(self, ticket_type: TicketType) -> None:
        """Add a category, using its name as the dictionary key."""
        key = ticket_type.name.lower()
        if key in self.ticket_types:
            raise ValueError(f"Ticket type '{ticket_type.name}' already exists.")

        self.ticket_types[key] = ticket_type

    def get_ticket_type(self, name: str) -> TicketType:
        """Find a category by name, ignoring letter case."""
        key = name.lower()
        if key not in self.ticket_types:
            raise ValueError(f"Ticket type '{name}' was not found.")

        return self.ticket_types[key]


class PricingEngine:
    """Calculate ticket prices from the percentage of capacity sold."""

    def calculate_price(self, ticket_type: TicketType) -> int:
        """Return the current unit price in paise.

        Below 50% sold: base price.
        From 50% to below 80% sold: 10% increase.
        At 80% sold or above: 20% increase.
        """
        sold_percent = ticket_type.tickets_sold / ticket_type.capacity

        if sold_percent >= 0.80:
            increase_percent = 20
        elif sold_percent >= 0.50:
            increase_percent = 10
        else:
            increase_percent = 0

        # Round to the nearest paise using integer arithmetic.
        return (ticket_type.base_price_paise * (100 + increase_percent) + 50) // 100


class BookingStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    PAYMENT_FAILED = "payment_failed"


class PaymentStatus(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Booking:
    """A record of tickets booked at a particular price."""

    booking_id: str
    event_id: str
    ticket_type_name: str
    quantity: int
    unit_price_paise: int
    payment_succeeded: bool | None
    created_at: datetime
    status: BookingStatus = BookingStatus.PENDING

    @property
    def total_price_paise(self) -> int:
        """Return the total charged for this booking."""
        return self.quantity * self.unit_price_paise

    def cancel(self) -> None:
        """Mark a pending or confirmed booking as cancelled."""
        if self.status is BookingStatus.CANCELLED:
            raise ValueError("This booking has already been cancelled.")
        if self.status is BookingStatus.PAYMENT_FAILED:
            raise ValueError("A booking with failed payment cannot be cancelled.")

        self.status = BookingStatus.CANCELLED


@dataclass
class Payment:
    """One simulated payment attempt for a booking."""

    booking_id: str
    amount_paise: int
    status: PaymentStatus
    created_at: datetime


class PaymentSimulator:
    """Simulate payment success or failure without collecting payment data."""

    def process_payment(self, amount_paise: int, should_succeed: bool = True) -> bool:
        """Return the chosen simulated outcome for a non-negative amount."""
        if amount_paise < 0:
            raise ValueError("Payment amount cannot be negative.")

        return should_succeed


class InMemoryStore:
    """Hold events and bookings in dictionaries for the prototype."""

    def __init__(self) -> None:
        self.events: dict[str, Event] = {}
        self.bookings: dict[str, Booking] = {}
        # A booking ID can have only one payment record.
        self.payments: dict[str, Payment] = {}

    def add_event(self, event: Event) -> None:
        if event.event_id in self.events:
            raise ValueError(f"Event '{event.event_id}' already exists.")

        self.events[event.event_id] = event

    def get_event(self, event_id: str) -> Event:
        if event_id not in self.events:
            raise ValueError(f"Event '{event_id}' was not found.")

        return self.events[event_id]

    def add_booking(self, booking: Booking) -> None:
        if booking.booking_id in self.bookings:
            raise ValueError(f"Booking '{booking.booking_id}' already exists.")

        self.bookings[booking.booking_id] = booking

    def get_booking(self, booking_id: str) -> Booking:
        if booking_id not in self.bookings:
            raise ValueError(f"Booking '{booking_id}' was not found.")

        return self.bookings[booking_id]

    def add_payment(self, payment: Payment) -> None:
        if payment.booking_id in self.payments:
            raise ValueError("A payment already exists for this booking.")

        self.payments[payment.booking_id] = payment


class BookingService:
    """Coordinate bookings, payment outcomes, and ticket inventory."""

    def __init__(
        self,
        store: InMemoryStore,
        pricing_engine: PricingEngine,
        payment_simulator: PaymentSimulator,
    ) -> None:
        self.store = store
        self.pricing_engine = pricing_engine
        self.payment_simulator = payment_simulator
        self._lock = Lock()

    def calculate_total(
        self, event_id: str, ticket_type_name: str, quantity: int
    ) -> int:
        """Quote the current total in paise for a positive quantity."""
        self._validate_selection(event_id, ticket_type_name, quantity)
        event = self.store.get_event(event_id)
        ticket_type = event.get_ticket_type(ticket_type_name)
        return self.pricing_engine.calculate_price(ticket_type) * quantity

    def create_booking(
        self, event_id: str, ticket_type_name: str, quantity: int
    ) -> Booking:
        """Reserve tickets and create a pending booking with a generated ID."""
        self._validate_selection(event_id, ticket_type_name, quantity)

        with self._lock:
            event = self.store.get_event(event_id)
            ticket_type = event.get_ticket_type(ticket_type_name)
            available = ticket_type.available_quantity()
            if quantity > available:
                raise ValueError(f"Only {available} tickets are available.")

            booking = Booking(
                booking_id=str(uuid4()),
                event_id=event.event_id,
                ticket_type_name=ticket_type.name,
                quantity=quantity,
                unit_price_paise=self.pricing_engine.calculate_price(ticket_type),
                payment_succeeded=None,
                created_at=datetime.now(),
            )

            # Reserve inventory while payment is pending.
            ticket_type.record_sale(quantity)
            try:
                self.store.add_booking(booking)
            except Exception:
                ticket_type.return_tickets(quantity)
                raise

            return booking

    def process_payment(
        self,
        booking_id: str,
        amount_paise: int,
        payment_should_succeed: bool = True,
    ) -> Payment:
        """Validate and process one payment for a pending booking.

        On failure, mark the booking failed and release its reserved tickets.
        """
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("Booking ID must be a non-empty string.")
        if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
            raise ValueError("Payment amount must be a whole number of paise.")
        if amount_paise < 0:
            raise ValueError("Payment amount cannot be negative.")
        if not isinstance(payment_should_succeed, bool):
            raise ValueError("Payment outcome must be True or False.")

        with self._lock:
            booking = self.store.get_booking(booking_id)
            if booking_id in self.store.payments:
                raise ValueError("A payment has already been processed for this booking.")
            if booking.status is not BookingStatus.PENDING:
                raise ValueError("Payment can only be processed for a pending booking.")
            if amount_paise != booking.total_price_paise:
                raise ValueError(
                    f"Payment amount must match the booking total "
                    f"({booking.total_price_paise} paise)."
                )

            succeeded = self.payment_simulator.process_payment(
                amount_paise, should_succeed=payment_should_succeed
            )
            payment = Payment(
                booking_id=booking.booking_id,
                amount_paise=amount_paise,
                status=PaymentStatus.SUCCEEDED if succeeded else PaymentStatus.FAILED,
                created_at=datetime.now(),
            )

            if succeeded:
                booking.payment_succeeded = True
                booking.status = BookingStatus.CONFIRMED
            else:
                event = self.store.get_event(booking.event_id)
                ticket_type = event.get_ticket_type(booking.ticket_type_name)
                ticket_type.return_tickets(booking.quantity)
                booking.payment_succeeded = False
                booking.status = BookingStatus.PAYMENT_FAILED

            self.store.add_payment(payment)
            return payment

    def view_booking(self, booking_id: str) -> Booking:
        """Return a booking by its ID."""
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("Booking ID must be a non-empty string.")

        return self.store.get_booking(booking_id)

    def cancel_booking(self, booking_id: str) -> Booking:
        """Cancel a pending or confirmed booking and release its tickets."""
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("Booking ID must be a non-empty string.")

        with self._lock:
            booking = self.store.get_booking(booking_id)
            if booking.status is BookingStatus.CANCELLED:
                raise ValueError("This booking has already been cancelled.")
            if booking.status is BookingStatus.PAYMENT_FAILED:
                raise ValueError("A booking with failed payment cannot be cancelled.")

            event = self.store.get_event(booking.event_id)
            ticket_type = event.get_ticket_type(booking.ticket_type_name)
            ticket_type.return_tickets(booking.quantity)
            booking.cancel()
            return booking

    @staticmethod
    def _validate_selection(
        event_id: str, ticket_type_name: str, quantity: int
    ) -> None:
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Event ID must be a non-empty string.")
        if not isinstance(ticket_type_name, str) or not ticket_type_name.strip():
            raise ValueError("Ticket type name must be a non-empty string.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("Quantity must be a positive whole number.")
