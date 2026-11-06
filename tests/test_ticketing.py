from datetime import date

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


@pytest.fixture
def setup_system():
    store = InMemoryStore()
    event = Event("event-1", "Python Live", date(2027, 5, 20), "A tech event")
    silver = TicketType("Silver", capacity=10, base_price_paise=10_000)
    gold = TicketType("Gold", capacity=5, base_price_paise=20_000)
    event.add_ticket_type(silver)
    event.add_ticket_type(gold)
    store.add_event(event)

    service = BookingService(store, PricingEngine(), PaymentSimulator())
    return store, event, silver, gold, service


def test_create_and_view_event(setup_system):
    store, event, _, _, _ = setup_system

    assert store.get_event("event-1") is event
    assert event.name == "Python Live"
    assert event.event_date == date(2027, 5, 20)


def test_create_different_ticket_types(setup_system):
    _, event, silver, gold, _ = setup_system

    assert event.get_ticket_type("silver") is silver
    assert event.get_ticket_type("GOLD") is gold


def test_reject_duplicate_ticket_type(setup_system):
    _, event, _, _, _ = setup_system

    with pytest.raises(ValueError, match="already exists"):
        event.add_ticket_type(TicketType("silver", capacity=3, base_price_paise=5_000))


def test_check_ticket_availability(setup_system):
    _, _, silver, _, _ = setup_system

    assert silver.available_quantity() == 10
    silver.record_sale(3)
    assert silver.available_quantity() == 7


def test_dynamic_price_changes_at_demand_thresholds(setup_system):
    _, _, silver, _, service = setup_system

    assert service.pricing_engine.calculate_price(silver) == 10_000
    silver.record_sale(5)
    assert service.pricing_engine.calculate_price(silver) == 11_000
    silver.record_sale(3)
    assert service.pricing_engine.calculate_price(silver) == 12_000


def test_successful_booking_and_payment_confirms_booking(setup_system):
    _, _, silver, _, service = setup_system

    booking = service.create_booking("event-1", "Silver", 2)
    assert booking.status is BookingStatus.PENDING
    assert silver.available_quantity() == 8

    payment = service.process_payment(booking.booking_id, booking.total_price_paise)

    assert payment.status is PaymentStatus.SUCCEEDED
    assert service.view_booking(booking.booking_id).status is BookingStatus.CONFIRMED
    assert booking.payment_succeeded is True


def test_reject_booking_when_tickets_are_sold_out(setup_system):
    _, _, silver, _, service = setup_system
    silver.record_sale(silver.capacity)

    with pytest.raises(ValueError, match="Only 0 tickets are available"):
        service.create_booking("event-1", "Silver", 1)


def test_reject_booking_when_requested_quantity_is_unavailable(setup_system):
    _, _, silver, _, service = setup_system
    silver.record_sale(8)

    with pytest.raises(ValueError, match="Only 2 tickets are available"):
        service.create_booking("event-1", "Silver", 3)


def test_failed_payment_marks_booking_failed_and_releases_inventory(setup_system):
    _, _, silver, _, service = setup_system
    booking = service.create_booking("event-1", "Silver", 2)
    assert silver.available_quantity() == 8

    payment = service.process_payment(
        booking.booking_id,
        booking.total_price_paise,
        payment_should_succeed=False,
    )

    assert payment.status is PaymentStatus.FAILED
    assert booking.status is BookingStatus.PAYMENT_FAILED
    assert booking.payment_succeeded is False
    assert silver.available_quantity() == 10


def test_reject_payment_amount_that_does_not_match_booking(setup_system):
    _, _, silver, _, service = setup_system
    booking = service.create_booking("event-1", "Silver", 1)

    with pytest.raises(ValueError, match="must match the booking total"):
        service.process_payment(booking.booking_id, booking.total_price_paise + 1)

    assert booking.status is BookingStatus.PENDING
    assert silver.available_quantity() == 9


def test_prevent_duplicate_payment_for_same_booking(setup_system):
    store, _, _, _, service = setup_system
    booking = service.create_booking("event-1", "Silver", 1)
    amount = booking.total_price_paise
    service.process_payment(booking.booking_id, amount)

    with pytest.raises(ValueError, match="already been processed"):
        service.process_payment(booking.booking_id, amount)

    assert len(store.payments) == 1


def test_cancel_confirmed_booking_and_restore_inventory(setup_system):
    _, _, silver, _, service = setup_system
    booking = service.create_booking("event-1", "Silver", 2)
    service.process_payment(booking.booking_id, booking.total_price_paise)

    cancelled = service.cancel_booking(booking.booking_id)

    assert cancelled.status is BookingStatus.CANCELLED
    assert silver.available_quantity() == 10


def test_prevent_duplicate_cancellation(setup_system):
    _, _, _, _, service = setup_system
    booking = service.create_booking("event-1", "Silver", 1)
    service.cancel_booking(booking.booking_id)

    with pytest.raises(ValueError, match="already been cancelled"):
        service.cancel_booking(booking.booking_id)


def test_handle_unknown_event_id(setup_system):
    _, _, _, _, service = setup_system

    with pytest.raises(ValueError, match="Event 'missing-event' was not found"):
        service.create_booking("missing-event", "Silver", 1)


def test_handle_unknown_booking_id(setup_system):
    _, _, _, _, service = setup_system

    with pytest.raises(ValueError, match="Booking 'missing-booking' was not found"):
        service.view_booking("missing-booking")


def test_reject_invalid_booking_quantity(setup_system):
    _, _, _, _, service = setup_system

    with pytest.raises(ValueError, match="positive whole number"):
        service.create_booking("event-1", "Silver", 0)

