from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("register/", views.register, name="register"),
    path("login/", views.sign_in, name="login"),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("models/", views.model_lab, name="model_lab"),
    path("parking/detect/", views.process_parking_image, name="process_image"),
    path("plates/", views.plate_list, name="plates"),
    path("plates/add/", views.add_plate, name="add_plate"),
    path("plates/<int:plate_id>/delete/", views.delete_plate, name="delete_plate"),
    path("history/", views.parking_history, name="history"),
    path("reports/export.csv", views.export_csv, name="export_csv"),
    path("notifications/read/", views.mark_notifications_read, name="notifications_read"),
    path("settings/tariff/", views.tariff_settings, name="tariff"),
    path("settings/blacklist/", views.blacklist, name="blacklist"),
    path("settings/blacklist/add/", views.add_blacklist_entry, name="add_blacklist"),
    path(
        "settings/blacklist/<int:entry_id>/remove/",
        views.remove_blacklist_entry,
        name="remove_blacklist",
    ),
]
