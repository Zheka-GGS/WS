from decimal import Decimal, ROUND_CEILING

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class VehiclePlate(models.Model):
    plate_number = models.CharField(max_length=16, unique=True, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vehicle_plates",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["plate_number"]
        verbose_name = "номерний знак"
        verbose_name_plural = "номерні знаки"

    def save(self, *args, **kwargs):
        self.plate_number = "".join(self.plate_number.upper().split()).replace("-", "")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.plate_number


class ParkingTariff(models.Model):
    name = models.CharField(max_length=80, default="Базовий тариф")
    hourly_rate = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("50.00"),
    )
    alert_limit = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("500.00"),
        help_text="Показати користувачу сповіщення, коли витрати досягнуть цієї суми.",
    )
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "name"]
        verbose_name = "тариф"
        verbose_name_plural = "тарифи"

    def save(self, *args, **kwargs):
        if self.is_active:
            ParkingTariff.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name}: {self.hourly_rate} грн/год"


class BlacklistEntry(models.Model):
    plate = models.OneToOneField(
        VehiclePlate,
        on_delete=models.CASCADE,
        related_name="blacklist_entry",
    )
    reason = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_blacklist_entries",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "запис чорного списку"
        verbose_name_plural = "чорний список"

    def __str__(self):
        return self.plate.plate_number


class ParkingSession(models.Model):
    plate = models.ForeignKey(
        VehiclePlate,
        on_delete=models.PROTECT,
        related_name="parking_sessions",
    )
    entry_at = models.DateTimeField(default=timezone.now, db_index=True)
    exit_at = models.DateTimeField(null=True, blank=True, db_index=True)
    hourly_rate = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    alert_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-entry_at"]
        indexes = [models.Index(fields=["plate", "exit_at"])]
        verbose_name = "паркування"
        verbose_name_plural = "паркування"

    @property
    def elapsed_seconds(self):
        end = self.exit_at or timezone.now()
        return max(0, int((end - self.entry_at).total_seconds()))

    @property
    def duration_display(self):
        seconds = self.elapsed_seconds
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f"{hours} год {minutes} хв"

    @property
    def total_cost(self):
        hours = max(1, int((Decimal(self.elapsed_seconds) / Decimal(3600)).to_integral_value(rounding=ROUND_CEILING)))
        return (self.hourly_rate * hours).quantize(Decimal("0.01"))

    @property
    def is_active(self):
        return self.exit_at is None

    def __str__(self):
        return f"{self.plate} · {self.entry_at:%Y-%m-%d %H:%M}"


class ParkingEvent(models.Model):
    EVENT_TYPES = [
        ("entry", "В'їзд"),
        ("exit", "Виїзд"),
        ("blocked", "Заблоковано"),
        ("unregistered", "Не зареєстровано"),
    ]
    plate = models.ForeignKey(
        VehiclePlate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    plate_text = models.CharField(max_length=16, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="parking_events",
    )
    event_type = models.CharField(max_length=16, choices=EVENT_TYPES)
    confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    details = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "подія розпізнавання"
        verbose_name_plural = "події розпізнавання"


class UserNotification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_notifications",
    )
    message = models.CharField(max_length=240)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "сповіщення"
        verbose_name_plural = "сповіщення"
