import csv
import time
from decimal import Decimal
from decimal import InvalidOperation

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    BlacklistForm,
    ModelTestForm,
    ParkingImageForm,
    RegistrationForm,
    VehiclePlateForm,
)
from .models import (
    BlacklistEntry,
    ParkingEvent,
    ParkingSession,
    UserNotification,
    VehiclePlate,
)
from .services import (
    current_tariff,
    normalize_plate,
    record_detection,
    refresh_cost_alerts,
)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Обліковий запис створено.")
        return redirect("dashboard")
    return render(request, "parking/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("dashboard")
    return render(request, "parking/login.html", {"form": form})


@login_required
def dashboard(request):
    refresh_cost_alerts(request.user)
    if request.user.is_staff:
        plates = VehiclePlate.objects.select_related("owner").filter(is_active=True)
        sessions = ParkingSession.objects.select_related("plate", "plate__owner")
        events = ParkingEvent.objects.select_related("plate", "actor")[:12]
        active_sessions = sessions.filter(exit_at__isnull=True)
    else:
        plates = VehiclePlate.objects.filter(owner=request.user, is_active=True)
        sessions = ParkingSession.objects.filter(plate__owner=request.user)
        events = ParkingEvent.objects.filter(plate__owner=request.user)[:12]
        active_sessions = sessions.filter(exit_at__isnull=True)
    total_cost = sum(
        (session.total_cost for session in sessions.filter(exit_at__isnull=False)),
        Decimal("0.00"),
    )
    notifications = UserNotification.objects.filter(user=request.user, read_at__isnull=True)[:5]
    return render(
        request,
        "parking/dashboard.html",
        {
            "plate_count": plates.count(),
            "plates": plates[:10],
            "active_sessions": active_sessions.select_related("plate")[:10],
            "active_count": active_sessions.count(),
            "recent_events": events,
            "notifications": notifications,
            "closed_session_count": sessions.filter(exit_at__isnull=False).count(),
            "tariff": current_tariff(),
            "total_billed": total_cost,
        },
    )


@login_required
def model_lab(request):
    result = None
    form = ModelTestForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["image"]
        if upload.size > settings.PARKVISION_MAX_UPLOAD_MB * 1024 * 1024:
            form.add_error("image", f"Максимальний розмір файла — {settings.PARKVISION_MAX_UPLOAD_MB} МБ.")
        else:
            started_at = time.perf_counter()
            try:
                response = httpx.post(
                    f"{settings.AI_SERVICE_URL}/api/predict/{form.cleaned_data['model_id']}",
                    files={"file": (upload.name, upload.read(), upload.content_type)},
                    timeout=120,
                )
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPStatusError as error:
                try:
                    detail = error.response.json().get("detail", "Помилка AI-сервісу.")
                except ValueError:
                    detail = "Помилка AI-сервісу."
                messages.error(request, str(detail))
            except httpx.RequestError:
                messages.error(
                    request,
                    "AI-сервіс недоступний. Переконайтеся, що запущено FastAPI на порту 8001.",
                )
            if result is not None:
                result["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000)
    return render(
        request,
        "parking/model_lab.html",
        {"form": form, "result": result},
    )


@login_required
def process_parking_image(request):
    result = None
    form = ParkingImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["image"]
        if upload.size > settings.PARKVISION_MAX_UPLOAD_MB * 1024 * 1024:
            form.add_error("image", f"Максимальний розмір файла — {settings.PARKVISION_MAX_UPLOAD_MB} МБ.")
        else:
            try:
                response = httpx.post(
                    f"{settings.AI_SERVICE_URL}/api/recognize",
                    files={"file": (upload.name, upload.read(), upload.content_type)},
                    timeout=120,
                )
                response.raise_for_status()
                prediction = response.json()
            except httpx.HTTPStatusError as error:
                try:
                    detail = error.response.json().get("detail", "Помилка AI-сервісу.")
                except ValueError:
                    detail = "Помилка AI-сервісу."
                messages.error(request, str(detail))
                prediction = None
            except httpx.RequestError:
                messages.error(request, "AI-сервіс недоступний. Запустіть FastAPI.")
                prediction = None

            if prediction is not None:
                prediction["confidence_percent"] = round(
                    float(prediction.get("confidence", 0)) * 100,
                    1,
                )
                plate_text = (
                    form.cleaned_data["plate_override"]
                    or prediction.get("plate_number", "")
                )
                result = {"prediction": prediction}
                if not plate_text:
                    result["event_message"] = (
                        "Номер не вдалося автоматично розпізнати. "
                        "Перевірте якість фото або введіть номер вручну."
                    )
                else:
                    try:
                        result["event"] = record_detection(
                            normalize_plate(plate_text),
                            request.user,
                            prediction.get("confidence"),
                            form.cleaned_data["event_direction"],
                        )
                        result["event_message"] = result["event"]["message"]
                    except ValueError as error:
                        result["event_message"] = str(error)
    return render(
        request,
        "parking/process_image.html",
        {"form": form, "result": result},
    )


@login_required
def plate_list(request):
    plates = VehiclePlate.objects.select_related("owner").prefetch_related(
        Prefetch("parking_sessions", queryset=ParkingSession.objects.all())
    )
    if not request.user.is_staff:
        plates = plates.filter(owner=request.user, is_active=True)
    plates = list(plates)
    for plate in plates:
        parking_sessions = list(plate.parking_sessions.all())
        total_seconds = sum(session.elapsed_seconds for session in parking_sessions)
        total_hours, remaining_seconds = divmod(total_seconds, 3600)
        total_minutes = remaining_seconds // 60
        plate.total_parking_duration = f"{total_hours} год {total_minutes} хв"
        plate.total_parking_cost = sum(
            (session.total_cost for session in parking_sessions),
            Decimal("0.00"),
        )
    return render(request, "parking/plates.html", {"plates": plates})


@login_required
def add_plate(request):
    if not request.user.is_staff:
        messages.error(request, "Додавати номерні знаки може лише адміністратор.")
        return redirect("plates")
    form = VehiclePlateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        plate = form.save()
        messages.success(request, f"Номер {plate.plate_number} зареєстровано.")
        return redirect("plates")
    return render(request, "parking/plate_form.html", {"form": form, "title": "Додати номер"})


@login_required
def delete_plate(request, plate_id):
    if request.method != "POST" or not request.user.is_staff:
        messages.error(request, "Видаляти номерні знаки може лише адміністратор.")
        return redirect("plates")
    plate = get_object_or_404(VehiclePlate, pk=plate_id)
    if plate.parking_sessions.filter(exit_at__isnull=True).exists():
        messages.error(request, "Неможливо видалити номер з активним паркуванням.")
    else:
        plate.is_active = False
        plate.save(update_fields=["is_active"])
        messages.success(request, "Номерний знак архівовано; історію паркувань збережено.")
    return redirect("plates")


@login_required
def parking_history(request):
    sessions = ParkingSession.objects.select_related("plate", "plate__owner")
    if not request.user.is_staff:
        sessions = sessions.filter(plate__owner=request.user)
    return render(request, "parking/history.html", {"sessions": sessions[:500]})


@login_required
def export_csv(request):
    sessions = ParkingSession.objects.select_related("plate", "plate__owner")
    if not request.user.is_staff:
        sessions = sessions.filter(plate__owner=request.user)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="parkvision-report.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        ["Номер", "Власник", "В'їзд", "Виїзд", "Тривалість", "Тариф грн/год", "Вартість грн"]
    )
    for session in sessions[:10000]:
        writer.writerow(
            [
                session.plate.plate_number,
                session.plate.owner.username,
                timezone.localtime(session.entry_at).strftime("%Y-%m-%d %H:%M:%S"),
                timezone.localtime(session.exit_at).strftime("%Y-%m-%d %H:%M:%S")
                if session.exit_at
                else "",
                session.duration_display,
                session.hourly_rate,
                session.total_cost,
            ]
        )
    return response


@login_required
@require_POST
def mark_notifications_read(request):
    UserNotification.objects.filter(user=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    messages.success(request, "Сповіщення позначено прочитаними.")
    return redirect("dashboard")


@login_required
def tariff_settings(request):
    if not request.user.is_staff:
        messages.error(request, "Змінювати тарифи може лише адміністратор.")
        return redirect("dashboard")
    tariff = current_tariff()
    if request.method == "POST":
        try:
            hourly_rate = Decimal(request.POST.get("hourly_rate", ""))
            alert_limit = Decimal(request.POST.get("alert_limit", ""))
            if hourly_rate < 0 or alert_limit < 0:
                raise ValueError
            tariff.hourly_rate = hourly_rate.quantize(Decimal("0.01"))
            tariff.alert_limit = alert_limit.quantize(Decimal("0.01"))
            tariff.save(update_fields=["hourly_rate", "alert_limit", "updated_at"])
            messages.success(request, "Тариф і ліміт сповіщення оновлено.")
            return redirect("tariff")
        except (ValueError, ArithmeticError, InvalidOperation):
            messages.error(request, "Вкажіть коректні невід'ємні суми.")
    return render(request, "parking/tariff.html", {"tariff": tariff})


@login_required
def blacklist(request):
    if not request.user.is_staff:
        messages.error(request, "Переглядати чорний список може лише адміністратор.")
        return redirect("dashboard")
    entries = BlacklistEntry.objects.select_related("plate", "plate__owner", "created_by")
    return render(request, "parking/blacklist.html", {"entries": entries})


@login_required
def add_blacklist_entry(request):
    if not request.user.is_staff:
        messages.error(request, "Змінювати чорний список може лише адміністратор.")
        return redirect("dashboard")
    form = BlacklistForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.created_by = request.user
        entry.save()
        messages.success(
            request,
            f"Номер {entry.plate.plate_number} додано до чорного списку.",
        )
        return redirect("blacklist")
    return render(
        request,
        "parking/plate_form.html",
        {"form": form, "title": "Додати до чорного списку"},
    )


@login_required
@require_POST
def remove_blacklist_entry(request, entry_id):
    if not request.user.is_staff:
        messages.error(request, "Змінювати чорний список може лише адміністратор.")
        return redirect("dashboard")
    entry = get_object_or_404(BlacklistEntry, pk=entry_id)
    plate_number = entry.plate.plate_number
    entry.delete()
    messages.success(request, f"Номер {plate_number} видалено з чорного списку.")
    return redirect("blacklist")
