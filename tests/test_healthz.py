"""Basic health and bootstrap tests for Step 0."""
import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_endpoint(client: Client) -> None:
    """Verifies that /healthz/ returns 200 OK plain text."""
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.content == b"OK"
    assert "text/plain" in response["Content-Type"]

@pytest.mark.django_db
def test_home_page_renders(client: Client) -> None:
    """Verifies that the home page renders with monochrome template."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Nightly Vocab" in response.content.decode("utf-8")
    assert "main.css" in response.content.decode("utf-8")
