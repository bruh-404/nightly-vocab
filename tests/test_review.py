"""Unit and integration tests for review session, queue building, Type 1-3, idempotency, and '!' modal (Step 6)."""
import json
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.cards.models import DailySession, ReviewLog, WordCard
from apps.texts.models import Text


@pytest.mark.django_db
class TestReviewSessionFlow:
    """Test suite for SRS daily review sessions and idempotency constraints."""

    @pytest.fixture
    def user(self):
        u = User.objects.create_user(username="reviewer@example.com", email="reviewer@example.com")
        u.profile.daily_limit = 10
        u.profile.save()
        return u

    @pytest.fixture
    def user_b(self):
        return User.objects.create_user(username="user_b@example.com", email="user_b@example.com")

    @pytest.fixture
    def client(self, user):
        c = Client()
        c.force_login(user)
        return c

    @pytest.fixture
    def source_text(self, user):
        return Text.objects.create(
            user=user,
            title="The Forest Path",
            body="We walked along the dark pathway. We felt safe and sound.",
        )

    @pytest.fixture
    def card_type1(self, user, source_text):
        return WordCard.objects.create(
            user=user,
            source_text=source_text,
            word="dark",
            lemma="dark",
            pos="adjective",
            meaning="تاریک",
            context_sentence="We walked along the dark pathway.",
            ctx_start=20,
            ctx_end=24,
            char_start=20,
            char_end=24,
            stage=1,
            target_type=1,
            next_review_date=user.profile.get_local_date(),
        )

    @pytest.fixture
    def card_type2(self, user, source_text):
        return WordCard.objects.create(
            user=user,
            source_text=source_text,
            word="pathway",
            lemma="pathway",
            pos="noun",
            meaning="مسیر، راه باریک",
            context_sentence="We walked along the dark pathway.",
            ctx_start=25,
            ctx_end=32,
            char_start=25,
            char_end=32,
            stage=3,
            target_type=2,
            next_review_date=user.profile.get_local_date(),
        )

    def test_review_shell_renders(self, client):
        res = client.get("/review/")
        assert res.status_code == 200
        assert "جلسه مرور شبانه" in res.content.decode("utf-8")

    def test_session_api_creates_daily_session_and_masks_type2(self, client, user, card_type1, card_type2):
        today = user.profile.get_local_date()
        res = client.get("/api/review/session/")
        assert res.status_code == 200
        data = res.json()

        assert data["done"] is False
        assert len(data["cards"]) == 2

        # Verify DailySession was created
        session = DailySession.objects.get(user=user, local_date=today)
        assert session.card_ids == [card_type1.id, card_type2.id]

        # Card Type 1 verification: word and meaning present
        c1 = [c for c in data["cards"] if c["id"] == card_type1.id][0]
        assert c1["display_type"] == 1
        assert c1["word"] == "dark"
        assert c1["meaning"] == "تاریک"

        # Card Type 2 verification: word and meaning MUST NOT be present in front view
        c2 = [c for c in data["cards"] if c["id"] == card_type2.id][0]
        assert c2["display_type"] == 2
        assert "word" not in c2
        assert "meaning" not in c2
        assert "_____" in c2["blanked_sentence"]
        assert len(c2["masked_boxes"]) == len("pathway")

        # Refresh consistency test: calling session again returns identical masked boxes
        res_refresh = client.get("/api/review/session/")
        data_refresh = res_refresh.json()
        c2_refresh = [c for c in data_refresh["cards"] if c["id"] == card_type2.id][0]
        assert c2["masked_boxes"] == c2_refresh["masked_boxes"]

    def test_recovery_banner_on_absence_over_7_days(self, client, user, card_type1):
        # Set last_active_date to 10 days ago
        user.profile.last_active_date = date.today() - timedelta(days=10)
        user.profile.save()

        res = client.get("/api/review/session/")
        assert res.status_code == 200
        data = res.json()
        assert data["recovery_banner"] is True

    def test_check_spelling_api(self, client, card_type2):
        # Correct spelling
        res = client.post(
            "/api/review/check/",
            data=json.dumps({"card_id": card_type2.id, "typed_input": "pathway"}),
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.json()
        assert data["spelling_correct"] is True
        assert data["word"] == "pathway"
        assert data["meaning"] == "مسیر، راه باریک"

        # Mistyped spelling
        res_wrong = client.post(
            "/api/review/check/",
            data=json.dumps({"card_id": card_type2.id, "typed_input": "pathwxy"}),
            content_type="application/json",
        )
        assert res_wrong.status_code == 200
        data_wrong = res_wrong.json()
        assert data_wrong["spelling_correct"] is False

    def test_submit_review_api_and_idempotency(self, client, user, card_type1):
        # Submit correct meaning for Type 1
        res = client.post(
            "/api/review/submit/",
            data=json.dumps({
                "card_id": card_type1.id,
                "display_type": 1,
                "meaning_correct": True,
            }),
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True

        today = user.profile.get_local_date()
        card_type1.refresh_from_db()
        assert card_type1.stage == 2  # Advanced from 1 to 2
        assert card_type1.last_reviewed_date == today

        # Check ReviewLog entry
        log = ReviewLog.objects.get(card=card_type1, local_date=today)
        assert log.meaning_correct is True
        assert log.stage_before == 1
        assert log.stage_after == 2

        # IDEMPOTENCY: submitting the same card twice on the same day returns 409 Conflict
        res_dup = client.post(
            "/api/review/submit/",
            data=json.dumps({
                "card_id": card_type1.id,
                "display_type": 1,
                "meaning_correct": True,
            }),
            content_type="application/json",
        )
        assert res_dup.status_code == 409
        assert "قبلاً مرور شده است" in res_dup.json()["error"]
        # Stage must not advance again
        card_type1.refresh_from_db()
        assert card_type1.stage == 2

    def test_context_modal_api(self, client, card_type1, source_text):
        res = client.get(f"/api/review/context/{card_type1.id}/")
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == source_text.title
        assert data["char_start"] == card_type1.char_start
        assert data["char_end"] == card_type1.char_end
        assert data["word"] == card_type1.word

    def test_idor_protection_on_all_endpoints(self, user_b, card_type1):
        client_b = Client()
        client_b.force_login(user_b)

        # Check spelling for another user's card -> 404
        res1 = client_b.post(
            "/api/review/check/",
            data=json.dumps({"card_id": card_type1.id, "typed_input": "dark"}),
            content_type="application/json",
        )
        assert res1.status_code == 404

        # Submit review for another user's card -> 404
        res2 = client_b.post(
            "/api/review/submit/",
            data=json.dumps({"card_id": card_type1.id, "meaning_correct": True}),
            content_type="application/json",
        )
        assert res2.status_code == 404

        # Get context for another user's card -> 404
        res3 = client_b.get(f"/api/review/context/{card_type1.id}/")
        assert res3.status_code == 404

    def test_card_type3_flow(self, client, user, source_text):
        # Create Type 3 card (stage 5)
        card3 = WordCard.objects.create(
            user=user,
            source_text=source_text,
            word="journey",
            lemma="journey",
            pos="noun",
            meaning="سفر",
            context_sentence="A long journey began.",
            ctx_start=7,
            ctx_end=14,
            char_start=7,
            char_end=14,
            stage=5,
            target_type=3,
            next_review_date=user.profile.get_local_date(),
        )

        res = client.get("/api/review/session/")
        assert res.status_code == 200
        data = res.json()
        c3_payload = [c for c in data["cards"] if c["id"] == card3.id][0]
        assert c3_payload["display_type"] == 3
        assert "word" not in c3_payload
        assert "meaning" not in c3_payload
        assert "_____" in c3_payload["blanked_sentence"]

        # Check spelling
        res_chk = client.post(
            "/api/review/check/",
            data=json.dumps({"card_id": card3.id, "typed_input": "journey"}),
            content_type="application/json",
        )
        assert res_chk.status_code == 200
        assert res_chk.json()["spelling_correct"] is True

        # Submit review
        res_sub = client.post(
            "/api/review/submit/",
            data=json.dumps({
                "card_id": card3.id,
                "display_type": 3,
                "typed_input": "journey",
                "meaning_correct": True,
            }),
            content_type="application/json",
        )
        assert res_sub.status_code == 200
        card3.refresh_from_db()
        assert card3.stage == 6  # Outcome 1: stage 5 -> 6

    def test_maintenance_quota_20_percent_integration(self, user):
        """Integration test verifying 20% maintenance cap for Bucket B (stage 5-8) cards."""
        user.profile.daily_limit = 20
        user.profile.save()

        # Seed 10 overdue Bucket B cards (stages 5 to 8)
        bucket_b_cards = []
        for i in range(10):
            c = WordCard.objects.create(
                user=user,
                word=f"advword{i}",
                lemma=f"advword{i}",
                pos="noun",
                meaning=f"معنی {i}",
                context_sentence=f"Context sentence for {i}.",
                ctx_start=0,
                ctx_end=4,
                stage=5 + (i % 4),  # stages 5, 6, 7, 8
                target_type=3,
                next_review_date=date.today() - timedelta(days=2),
            )
            bucket_b_cards.append(c)

        # Seed 20 overdue Bucket A cards (stages 1 to 4)
        bucket_a_cards = []
        for i in range(20):
            c = WordCard.objects.create(
                user=user,
                word=f"basicword{i}",
                lemma=f"basicword{i}",
                pos="noun",
                meaning=f"معنی ساده {i}",
                context_sentence=f"Context sentence for basic {i}.",
                ctx_start=0,
                ctx_end=5,
                stage=1 + (i % 4),  # stages 1, 2, 3, 4
                target_type=1,
                next_review_date=date.today() - timedelta(days=2),
            )
            bucket_a_cards.append(c)

        client = Client()
        client.force_login(user)

        res = client.get("/api/review/session/")
        assert res.status_code == 200
        data = res.json()
        assert data["done"] is False
        assert len(data["cards"]) == 20

        # Verify exactly 4 cards from Bucket B (20% of 20 = 4) and 16 cards from Bucket A
        b_ids = {c.id for c in bucket_b_cards}
        a_ids = {c.id for c in bucket_a_cards}

        selected_ids = [c["id"] for c in data["cards"]]
        b_selected = [cid for cid in selected_ids if cid in b_ids]
        a_selected = [cid for cid in selected_ids if cid in a_ids]

        assert len(b_selected) == 4
        assert len(a_selected) == 16
