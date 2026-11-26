from decimal import Decimal
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import torch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (
    BlacklistEntry,
    ParkingEvent,
    ParkingSession,
    ParkingTariff,
    UserNotification,
    VehiclePlate,
)
from .services import normalize_plate, record_detection
from model_inference import recognize_plate


User = get_user_model()


def small_jpeg():
    buffer = BytesIO()
    Image.new("RGB", (48, 32), "white").save(buffer, format="JPEG")
    return SimpleUploadedFile("test.jpg", buffer.getvalue(), "image/jpeg")


class RecognitionAnnotationTests(TestCase):
    @patch("model_inference._predict_plate")
    @patch("model_inference.load_model")
    def test_vehicle_result_draws_bbox_and_recognized_plate(self, load_model, predict_ocr):
        class FakeBoxes:
            conf = torch.tensor([0.97])
            xyxy = torch.tensor([[30, 35, 220, 95]])

            def __len__(self):
                return len(self.conf)

        boxes = FakeBoxes()
        detector = SimpleNamespace(
            predict=lambda **kwargs: [SimpleNamespace(boxes=boxes)]
        )
        load_model.side_effect = lambda model_id: detector if model_id == "lpr_detector" else object()
        predict_ocr.return_value = ("AA1234BB", 0.94, None)
        image = np.zeros((150, 300, 3), dtype=np.uint8)

        plate, confidence, annotated, message = recognize_plate(image)

        self.assertEqual(plate, "AA1234BB")
        self.assertAlmostEqual(confidence, 0.97, places=2)
        self.assertEqual(annotated.shape, image.shape)
        self.assertTrue(np.any(annotated != image))
        self.assertIn("AA1234BB", message)
        self.assertIn("94.0%", message)


class PlateNormalizationTests(TestCase):
    def test_normalizes_spaces_and_case(self):
        self.assertEqual(normalize_plate(" aa 0071 pp "), "AA0071PP")

    def test_rejects_unexpected_characters(self):
        with self.assertRaises(ValueError):
            normalize_plate("AA/0071")


class ParkingEventTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="safe-test-password")
        self.operator = User.objects.create_user(username="operator", password="safe-test-password")
        self.plate = VehiclePlate.objects.create(
            plate_number="AA 0071 PP",
            owner=self.owner,
        )
        self.tariff = ParkingTariff.objects.create(
            name="Test",
            hourly_rate=Decimal("25.00"),
            alert_limit=Decimal("1000.00"),
        )

    def test_recognitions_toggle_entry_and_exit_and_store_billing(self):
        entry = record_detection("aa0071pp", self.operator, 0.95)
        self.assertEqual(entry["event"], "entry")
        session = ParkingSession.objects.get(plate=self.plate, exit_at__isnull=True)
        self.assertEqual(session.hourly_rate, Decimal("25.00"))

        exit_result = record_detection("AA0071PP", self.operator, 0.92)
        session.refresh_from_db()
        self.assertEqual(exit_result["event"], "exit")
        self.assertIsNotNone(session.exit_at)
        self.assertEqual(session.total_cost, Decimal("25.00"))
        self.assertEqual(
            list(ParkingEvent.objects.values_list("event_type", flat=True)),
            ["exit", "entry"],
        )

    def test_unregistered_and_blacklisted_plates_do_not_start_sessions(self):
        result = record_detection("BB1234CC", self.operator)
        self.assertEqual(result["event"], "unregistered")

        BlacklistEntry.objects.create(
            plate=self.plate,
            created_by=self.operator,
            reason="Тест",
        )
        blocked = record_detection("AA0071PP", self.operator)
        self.assertEqual(blocked["event"], "blocked")
        self.assertFalse(ParkingSession.objects.exists())

    def test_explicit_entry_and_exit_do_not_toggle_on_duplicate_uploads(self):
        entry = record_detection("AA0071PP", self.operator, direction="entry")
        repeated_entry = record_detection("AA0071PP", self.operator, direction="entry")
        self.assertEqual(entry["event"], "entry")
        self.assertEqual(repeated_entry["event"], "already_parked")
        self.assertEqual(ParkingSession.objects.filter(plate=self.plate, exit_at__isnull=True).count(), 1)

        exit_result = record_detection("AA0071PP", self.operator, direction="exit")
        repeated_exit = record_detection("AA0071PP", self.operator, direction="exit")
        self.assertEqual(exit_result["event"], "exit")
        self.assertEqual(repeated_exit["event"], "no_active_session")

    def test_cost_threshold_creates_a_user_notification(self):
        self.tariff.alert_limit = Decimal("1.00")
        self.tariff.save()
        record_detection("AA0071PP", self.operator)
        self.assertTrue(
            UserNotification.objects.filter(user=self.owner).exists()
        )


class WebAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="safe-test-password")
        self.other = User.objects.create_user(username="other", password="safe-test-password")
        self.plate = VehiclePlate.objects.create(
            plate_number="AA0071PP",
            owner=self.owner,
        )

    def test_dashboard_requires_login_and_registered_users_see_their_plate(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

        self.client.login(username="owner", password="safe-test-password")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AA0071PP")

    def test_users_cannot_view_another_users_plate(self):
        self.client.login(username="other", password="safe-test-password")
        response = self.client.get(reverse("plates"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AA0071PP")

    def test_csv_export_is_scoped_to_the_current_user(self):
        other_plate = VehiclePlate.objects.create(
            plate_number="BB1234CC",
            owner=self.other,
        )
        ParkingSession.objects.create(
            plate=self.plate,
            hourly_rate=Decimal("20.00"),
            entry_at=timezone.now(),
        )
        ParkingSession.objects.create(
            plate=other_plate,
            hourly_rate=Decimal("30.00"),
            entry_at=timezone.now(),
        )
        self.client.login(username="owner", password="safe-test-password")
        response = self.client.get(reverse("export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AA0071PP")
        self.assertNotContains(response, "BB1234CC")

    def test_registration_creates_a_regular_user(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new-driver",
                "email": "new-driver@example.test",
                "password1": "Strong-test-password-2026!",
                "password2": "Strong-test-password-2026!",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(username="new-driver")
        self.assertFalse(created.is_staff)
        self.assertIn("_auth_user_id", self.client.session)

    @patch("parking.views.httpx.post")
    def test_recognition_form_requires_explicit_direction_and_duplicate_entry_is_safe(self, post):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "plate_number": "AA0071PP",
                    "confidence": 0.95,
                    "message": "Recognized plate",
                    "annotated_image": None,
                }

        post.return_value = FakeResponse()
        self.client.login(username="owner", password="safe-test-password")
        for _ in range(2):
            response = self.client.post(
                reverse("process_image"),
                {
                    "image": small_jpeg(),
                    "event_direction": "entry",
                    "plate_override": "",
                },
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(
            ParkingSession.objects.filter(plate=self.plate, exit_at__isnull=True).count(),
            1,
        )
        self.assertEqual(
            list(ParkingEvent.objects.values_list("event_type", flat=True)),
            ["entry"],
        )

    def test_staff_can_register_a_plate_and_archiving_preserves_history(self):
        admin = User.objects.create_superuser(
            username="admin",
            password="safe-admin-password",
            email="admin@example.test",
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("add_plate"),
            {"plate_number": "BB 1234 CC", "owner": self.other.pk},
        )
        self.assertEqual(response.status_code, 302)
        plate = VehiclePlate.objects.get(plate_number="BB1234CC")
        started = timezone.now()
        session = ParkingSession.objects.create(
            plate=plate,
            hourly_rate=Decimal("20.00"),
            entry_at=started,
            exit_at=started,
        )
        response = self.client.post(reverse("delete_plate", args=[plate.pk]))
        self.assertEqual(response.status_code, 302)
        plate.refresh_from_db()
        self.assertFalse(plate.is_active)
        self.assertTrue(ParkingSession.objects.filter(pk=session.pk).exists())

    def test_regular_user_cannot_change_tariff(self):
        self.client.login(username="owner", password="safe-test-password")
        response = self.client.post(
            reverse("tariff"),
            {"hourly_rate": "1.00", "alert_limit": "1.00"},
        )
        self.assertEqual(response.url, reverse("dashboard"))
        tariff = ParkingTariff.objects.get(is_active=True)
        self.assertEqual(tariff.hourly_rate, Decimal("50.00"))
        self.assertEqual(tariff.alert_limit, Decimal("500.00"))

    def test_staff_can_update_tariff_and_manage_blacklist(self):
        admin = User.objects.create_superuser(
            username="admin",
            password="safe-admin-password",
            email="admin@example.test",
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("tariff"),
            {"hourly_rate": "75.50", "alert_limit": "250.00"},
        )
        self.assertEqual(response.status_code, 302)
        tariff = ParkingTariff.objects.get(is_active=True)
        self.assertEqual(tariff.hourly_rate, Decimal("75.50"))
        self.assertEqual(tariff.alert_limit, Decimal("250.00"))

        response = self.client.post(
            reverse("add_blacklist"),
            {"plate": self.plate.pk, "reason": "Тестова причина"},
        )
        self.assertEqual(response.status_code, 302)
        entry = BlacklistEntry.objects.get(plate=self.plate)
        self.assertEqual(entry.created_by, admin)
        response = self.client.post(reverse("remove_blacklist", args=[entry.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlacklistEntry.objects.filter(plate=self.plate).exists())

    def test_dashboard_creates_notification_when_live_cost_reaches_limit(self):
        tariff = ParkingTariff.objects.create(
            name="Alert test",
            hourly_rate=Decimal("50.00"),
            alert_limit=Decimal("50.00"),
        )
        ParkingSession.objects.create(
            plate=self.plate,
            hourly_rate=tariff.hourly_rate,
            entry_at=timezone.now() - timedelta(hours=2),
        )
        self.client.login(username="owner", password="safe-test-password")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserNotification.objects.filter(user=self.owner).exists())

    @patch("parking.views.httpx.post")
    def test_model_lab_upload_returns_selected_model_output(self, post):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "message": "Вільне місце · впевненість 99.0%",
                    "annotated_image": None,
                    "inference_time_ms": 14,
                }

        post.return_value = FakeResponse()
        self.client.login(username="owner", password="safe-test-password")
        response = self.client.post(
            reverse("model_lab"),
            {
                "model_id": "parking_occupancy",
                "image": small_jpeg(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вільне місце")
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:8001/api/predict/parking_occupancy")
