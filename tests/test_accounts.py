"""Unit tests for accounts, profile signal, adapters, and timezone sync."""
import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory

from apps.accounts.adapter import AccountAdapter, SocialAccountAdapter
from apps.accounts.models import validate_card_types

User = get_user_model()

@pytest.mark.django_db
def test_profile_auto_created_on_user_save() -> None:
    """A Profile with default settings must be created automatically when a User is created."""
    user = User.objects.create_user(username="testuser", email="test@example.com")
    assert hasattr(user, "profile")
    profile = user.profile
    assert profile.daily_limit == 20
    assert profile.enabled_card_types == [1, 2, 3]
    assert profile.accent == "uk"
    assert profile.timezone == "UTC"
    assert profile.ai_example_enabled is False
    assert profile.reminder_enabled is False

@pytest.mark.django_db
def test_card_types_validator() -> None:
    """Validates that enabled_card_types allows non-empty subsets of {1, 2, 3}."""
    validate_card_types([1])
    validate_card_types([1, 2])
    validate_card_types([1, 2, 3])
    validate_card_types([2, 3])

    with pytest.raises(ValidationError):
        validate_card_types([])

    with pytest.raises(ValidationError):
        validate_card_types([1, 4])

    with pytest.raises(ValidationError):
        validate_card_types("not-a-list")

@pytest.mark.django_db
def test_account_adapter_blocks_local_signup() -> None:
    """Local username/password signup must be completely closed."""
    adapter = AccountAdapter()
    factory = RequestFactory()
    request = factory.get("/accounts/signup/")
    assert adapter.is_open_for_signup(request) is False

@pytest.mark.django_db
def test_social_account_adapter_allowlist(settings) -> None:
    """Social adapter allows all if ALLOWED_EMAILS is empty, or only allowlisted emails."""
    adapter = SocialAccountAdapter()
    factory = RequestFactory()
    request = factory.get("/")

    # 1. No ALLOWED_EMAILS set
    settings.ALLOWED_EMAILS = []
    user_any = User(email="anyone@gmail.com")
    social_login_any = SocialLogin(user=user_any)
    assert adapter.is_open_for_signup(request, social_login_any) is True

    # 2. ALLOWED_EMAILS set
    settings.ALLOWED_EMAILS = ["vip@example.com", "owner@gmail.com"]

    user_allowed = User(email="vip@example.com")
    social_login_allowed = SocialLogin(user=user_allowed)
    assert adapter.is_open_for_signup(request, social_login_allowed) is True
    # pre_social_login should pass without exception
    adapter.pre_social_login(request, social_login_allowed)

    user_denied = User(email="stranger@gmail.com")
    social_login_denied = SocialLogin(user=user_denied)
    assert adapter.is_open_for_signup(request, social_login_denied) is False
    with pytest.raises(ImmediateHttpResponse) as excinfo:
        adapter.pre_social_login(request, social_login_denied)
    assert excinfo.value.response.status_code == 403

@pytest.mark.django_db
def test_timezone_sync_endpoint(client: Client) -> None:
    """Test timezone sync endpoint for authenticated vs anonymous users."""
    url = "/api/accounts/timezone/"

    # Anonymous user gets redirected
    res_anon = client.post(url, data='{"timezone": "Asia/Tehran"}', content_type="application/json")
    assert res_anon.status_code == 302

    # Authenticated user
    user = User.objects.create_user(username="tzuser", email="tz@example.com")
    client.force_login(user)

    # Valid timezone
    res = client.post(url, data='{"timezone": "Asia/Tehran"}', content_type="application/json")
    assert res.status_code == 200
    assert res.json()["success"] is True
    user.profile.refresh_from_db()
    assert user.profile.timezone == "Asia/Tehran"

    # Invalid timezone returns 400
    res_bad = client.post(url, data='{"timezone": "Invalid/Fake_Zone"}', content_type="application/json")
    assert res_bad.status_code == 400

@pytest.mark.django_db
def test_dashboard_requires_login(client: Client) -> None:
    """Dashboard requires authentication."""
    res_anon = client.get("/dashboard/")
    assert res_anon.status_code == 302
    assert "/" in res_anon["Location"]

    user = User.objects.create_user(username="dashuser", email="dash@example.com")
    client.force_login(user)
    res_auth = client.get("/dashboard/")
    assert res_auth.status_code == 200
    assert "داشبورد" in res_auth.content.decode("utf-8")

@pytest.mark.django_db
def test_home_redirects_authenticated_user(client: Client) -> None:
    """Accessing root / redirects authenticated users to /dashboard/."""
    user = User.objects.create_user(username="homeuser", email="home@example.com")
    client.force_login(user)
    res = client.get("/")
    assert res.status_code == 302
    assert "/dashboard/" in res["Location"]
