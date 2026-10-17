"""URL patterns for texts app."""
from django.urls import path

from .views import (
    analyze_text_api,
    save_cards_api,
    text_create_view,
    text_delete_api,
    text_detail_view,
    text_list_view,
    text_select_view,
)

app_name = "texts"

urlpatterns = [
    path("texts/", text_list_view, name="list"),
    path("texts/new/", text_create_view, name="create"),
    path("texts/<int:text_id>/", text_detail_view, name="detail"),
    path("texts/<int:text_id>/select/", text_select_view, name="select"),
    path("api/texts/<int:text_id>/analyze/", analyze_text_api, name="analyze_text_api"),
    path("api/texts/<int:text_id>/cards/", save_cards_api, name="save_cards_api"),
    path("api/texts/<int:text_id>/delete/", text_delete_api, name="delete_text_api"),
]
