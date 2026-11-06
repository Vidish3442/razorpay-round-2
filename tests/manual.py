from datetime import date
from concurrent.futures import ThreadPoolExecutor

import pytest

from ticketing import (
    BookingService,
    BookingStatus,
    Event,
    InMemoryStore,
    PaymentSimulator,
    PaymentStatus,
    PricingEngine,
    TicketType,
)

store = InMemoryStore()

event = Event("event-1", "Python Live", date(2027, 5, 20), "A tech event")

silver = TicketType("Silver", capacity=10, base_price_paise=10_000)
gold = TicketType("Gold", capacity=1, base_price_paise=20_000)

event.add_ticket_type(silver)
event.add_ticket_type(gold)
store.add_event(event)

service = BookingService(store, PricingEngine(), PaymentSimulator())

def bookticket(user):
    try:
        booking = service.create_booking("event-1", "Gold", 1)
        return f"User {user}: Booking ID: {booking.booking_id}, Status: {booking.status}"
    except ValueError as e:
        return f"User {user}: Booking rejected: {e}"


with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(bookticket, [101, 102]))

for result in results:
    print(result)

print("\nRemaining Gold tickets:", gold.available_quantity())