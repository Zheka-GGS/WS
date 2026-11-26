import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    BlacklistEntry,
    ParkingEvent,
    ParkingSession,
    ParkingTariff,
    UserNotification,
    VehiclePlate,
)


def normalize_plate(value):
    plate = re.sub(r"[\s-]", "", value or "").upper()
    if not re.fullmatch(r"[A-Z0-9]{5,10}", plate):
        raise ValueError("Номерний знак має містити 5–10 латинських літер або цифр.")
    return plate


def current_tariff():
    tariff = ParkingTariff.objects.filter(is_active=True).order_by("-updated_at").first()
    if tariff:
        return tariff
    return ParkingTariff.objects.create(
        name="Базовий тариф",
        hourly_rate=Decimal("50.00"),
        alert_limit=Decimal("500.00"),
        is_active=True,
    )


def _check_cost_alert(session):
    tariff = current_tariff()
    if session.alert_sent_at is None and session.total_cost >= tariff.alert_limit:
        UserNotification.objects.create(
            user=session.plate.owner,
            message=(
                f"Витрати за паркуванням {session.plate.plate_number} "
                f"досягли {session.total_cost:.2f} грн."
            ),
        )
        session.alert_sent_at = timezone.now()
        session.save(update_fields=["alert_sent_at"])


def refresh_cost_alerts(user):
    sessions = ParkingSession.objects.filter(
        exit_at__isnull=True,
        alert_sent_at__isnull=True,
    )
    if not user.is_staff:
        sessions = sessions.filter(plate__owner=user)
    for session in sessions.select_related("plate", "plate__owner"):
        _check_cost_alert(session)


@transaction.atomic
def record_detection(raw_plate, actor, confidence=None, direction="auto"):
    if direction not in {"auto", "entry", "exit"}:
        raise ValueError("Тип події має бути в'їздом або виїздом.")
    plate_text = normalize_plate(raw_plate)
    plate = VehiclePlate.objects.select_for_update().filter(
        plate_number=plate_text,
        is_active=True,
    ).first()
    if plate is None:
        ParkingEvent.objects.create(
            plate_text=plate_text,
            actor=actor,
            event_type="unregistered",
            confidence=confidence,
            details="Номер не знайдено серед зареєстрованих транспортних засобів.",
        )
        return {
            "event": "unregistered",
            "plate": plate_text,
            "message": f"Номер {plate_text} не зареєстрований.",
        }

    if BlacklistEntry.objects.filter(plate=plate).exists():
        ParkingEvent.objects.create(
            plate=plate,
            plate_text=plate_text,
            actor=actor,
            event_type="blocked",
            confidence=confidence,
            details="Транспортний засіб у чорному списку.",
        )
        return {
            "event": "blocked",
            "plate": plate_text,
            "message": f"В'їзд для {plate_text} заблоковано.",
        }

    session = (
        ParkingSession.objects.select_for_update()
        .filter(plate=plate, exit_at__isnull=True)
        .first()
    )
    if direction == "entry" and session is not None:
        return {
            "event": "already_parked",
            "plate": plate_text,
            "message": f"Для {plate_text} вже є активне паркування; повторний в'їзд не створено.",
        }
    if direction == "exit" and session is None:
        return {
            "event": "no_active_session",
            "plate": plate_text,
            "message": f"Для {plate_text} немає активного паркування, яке можна завершити.",
        }
    if session:
        session.exit_at = timezone.now()
        session.save(update_fields=["exit_at"])
        ParkingEvent.objects.create(
            plate=plate,
            plate_text=plate_text,
            actor=actor,
            event_type="exit",
            confidence=confidence,
            details=f"Тривалість {session.duration_display}; вартість {session.total_cost:.2f} грн.",
        )
        UserNotification.objects.create(
            user=plate.owner,
            message=(
                f"Паркування {plate_text} завершено. "
                f"Вартість: {session.total_cost:.2f} грн."
            ),
        )
        _check_cost_alert(session)
        return {
            "event": "exit",
            "plate": plate_text,
            "duration": session.duration_display,
            "cost": str(session.total_cost),
            "message": (
                f"Виїзд {plate_text} зафіксовано. "
                f"{session.duration_display} · {session.total_cost:.2f} грн."
            ),
        }

    tariff = current_tariff()
    session = ParkingSession.objects.create(
        plate=plate,
        hourly_rate=tariff.hourly_rate,
    )
    ParkingEvent.objects.create(
        plate=plate,
        plate_text=plate_text,
        actor=actor,
        event_type="entry",
        confidence=confidence,
        details=f"Тариф {session.hourly_rate:.2f} грн/год.",
    )
    _check_cost_alert(session)
    return {
        "event": "entry",
        "plate": plate_text,
        "message": f"В'їзд {plate_text} зафіксовано.",
    }
