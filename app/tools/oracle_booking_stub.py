from app.config import load_settings
from app.tools.oracle_availability import OracleAvailabilityClient
from app.tools.oracle_cancellation import OracleCancellationClient
from app.tools.oracle_reservation_create import OracleReservationCreateClient


def check_availability(booking, settings=None, reference_date=None):
    return OracleAvailabilityClient(settings or load_settings()).check_availability(
        booking,
        reference_date=reference_date,
    )


def create_booking(booking, settings=None, reference_date=None, custom_reference=None):
    return OracleReservationCreateClient(settings or load_settings()).create_reservation(
        booking,
        reference_date=reference_date,
        custom_reference=custom_reference,
    )


def cancel_booking(confirmation_number, settings=None):
    return OracleCancellationClient(settings or load_settings()).cancel_by_confirmation(confirmation_number)


def modify_booking(*args, **kwargs):
    raise NotImplementedError("Oracle modification is intentionally disabled.")
