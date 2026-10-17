"""URLs for cards app (Library & Card actions)."""
from django.urls import path

from . import views

app_name = "cards"

urlpatterns = [
    path("library/", views.library_view, name="library"),
    path("api/cards/new/", views.manual_add_card_api, name="manual_add_card"),
    path("api/cards/<int:card_id>/edit/", views.edit_card_api, name="edit_card"),
    path("api/cards/<int:card_id>/suspend/", views.toggle_suspend_card_api, name="toggle_suspend_card"),
    path("api/cards/<int:card_id>/reset/", views.reset_card_progress_api, name="reset_card_progress"),
    path("api/cards/<int:card_id>/delete/", views.delete_card_api, name="delete_card"),
]
