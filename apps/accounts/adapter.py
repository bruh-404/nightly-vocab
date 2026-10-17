"""Custom Allauth adapters for Nightly Vocab."""
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest
from django.shortcuts import render


class AccountAdapter(DefaultAccountAdapter):
    """Account adapter disabling standard local (username/password) signups."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        # Standard username/password registration is completely disabled
        return False

class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Social account adapter enforcing Google OAuth and optional email allowlist."""

    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any) -> bool:
        allowed = getattr(settings, "ALLOWED_EMAILS", [])
        if not allowed:
            return True

        email = sociallogin.user.email
        return bool(email and email.strip().lower() in [e.strip().lower() for e in allowed])

    def pre_social_login(self, request: HttpRequest, sociallogin: Any) -> None:
        allowed = getattr(settings, "ALLOWED_EMAILS", [])
        if not allowed:
            return

        email = sociallogin.user.email
        normalized_allowed = [e.strip().lower() for e in allowed]
        if not email or email.strip().lower() not in normalized_allowed:
            # Render a clean monochrome unauthorized message
            context = {
                "user_email": email or "نامشخص",
            }
            response = render(request, "account_not_allowed.html", context, status=403)
            raise ImmediateHttpResponse(response)
