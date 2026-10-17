"""URL routing for review app."""
from django.urls import path

from .views import (
    check_spelling_api,
    get_card_context_api,
    get_review_session_api,
    review_shell_view,
    submit_review_api,
)

app_name = "review"

urlpatterns = [
    path("review/", review_shell_view, name="session"),
    path("api/review/session/", get_review_session_api, name="session_api"),
    path("api/review/check/", check_spelling_api, name="check_api"),
    path("api/review/submit/", submit_review_api, name="submit_api"),
    path("api/review/context/<int:card_id>/", get_card_context_api, name="context_api"),
]
