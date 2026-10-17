from typing import Any, Dict
from django.http import HttpRequest


def site_config(request: HttpRequest) -> Dict[str, Any]:
    """Provides global site_config in all template rendering contexts."""
    try:
        from apps.services.models import SiteConfig
        return {"site_config": SiteConfig.get()}
    except Exception:
        return {"site_config": None}
