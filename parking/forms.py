from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import BlacklistEntry, VehiclePlate


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")


class ModelTestForm(forms.Form):
    model_id = forms.ChoiceField(
        choices=[
            ("lpr_detector", "Детектор номерного знака · LPR"),
            ("character_recognition", "Розпізнавання символів · OCR"),
            ("parking_occupancy", "Класифікатор паркомісця · PKLot"),
        ],
        label="Готова модель",
    )
    image = forms.ImageField(label="Зображення")


class ParkingImageForm(forms.Form):
    image = forms.ImageField(label="Фото автомобіля")
    event_direction = forms.ChoiceField(
        choices=[("entry", "В'їзд"), ("exit", "Виїзд")],
        initial="entry",
        label="Тип події",
    )
    plate_override = forms.CharField(
        label="Номер для виправлення OCR (необов'язково)",
        required=False,
        max_length=16,
        help_text="Якщо автоматичне розпізнавання помилилося, введіть номер із реєстру.",
    )


class VehiclePlateForm(forms.ModelForm):
    class Meta:
        model = VehiclePlate
        fields = ("plate_number", "owner")

    owner = forms.ModelChoiceField(
        queryset=get_user_model().objects.order_by("username"),
        label="Власник",
    )


class BlacklistForm(forms.ModelForm):
    class Meta:
        model = BlacklistEntry
        fields = ("plate", "reason")
        labels = {"plate": "Номерний знак", "reason": "Причина"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plate"].queryset = VehiclePlate.objects.filter(is_active=True)
