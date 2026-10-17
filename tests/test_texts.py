"""Unit and integration tests for texts app, tokenizer, views, and card creation API."""
import json

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client

from apps.cards.models import WordCard
from apps.texts.models import Text
from apps.texts.tokenizer import (
    extract_sentence_for_span,
    is_abbreviation_at,
    tokenize_text,
)


@pytest.mark.django_db
class TestTokenizer:
    """Test suite for server-side tokenization and sentence boundary detection."""

    def test_basic_tokenization(self):
        body = "The quick brown fox jumps over the lazy dog."
        tokens = tokenize_text(body)

        assert len(tokens) == 9
        words = [t.text for t in tokens]
        assert words == [
            "The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"
        ]

        # Verify exact string slices
        for t in tokens:
            assert body[t.start : t.end] == t.text
            assert t.sent_idx == 0

    def test_contractions_and_unicode_apostrophe(self):
        body = "Don't let them say you can’t make it."
        tokens = tokenize_text(body)
        words = [t.text for t in tokens]

        assert "Don't" in words
        assert "can’t" in words
        for t in tokens:
            assert body[t.start : t.end] == t.text

    def test_hyphenated_words(self):
        body = "This is a state-of-the-art algorithm."
        tokens = tokenize_text(body)
        words = [t.text for t in tokens]

        assert "state-of-the-art" in words
        target = [t for t in tokens if t.text == "state-of-the-art"][0]
        assert body[target.start : target.end] == "state-of-the-art"

    def test_abbreviation_sentence_protection(self):
        body = "Dr. Smith called Mr. Brown yesterday. They discussed e.g. language models."
        tokens = tokenize_text(body)

        # "Dr." period shouldn't split sentence; sentence 0 should contain Smith and Brown
        dr_tok = [t for t in tokens if t.text == "Dr"][0]
        smith_tok = [t for t in tokens if t.text == "Smith"][0]
        brown_tok = [t for t in tokens if t.text == "Brown"][0]
        they_tok = [t for t in tokens if t.text == "They"][0]

        assert dr_tok.sent_idx == smith_tok.sent_idx == brown_tok.sent_idx == 0
        assert they_tok.sent_idx == 1

    def test_sentence_split_with_quotes_and_newlines(self):
        body = 'She said, "Safe and sound!"\n\nThen he smiled.'
        tokens = tokenize_text(body)

        she_tok = [t for t in tokens if t.text == "She"][0]
        then_tok = [t for t in tokens if t.text == "Then"][0]

        assert she_tok.sent_idx == 0
        assert then_tok.sent_idx == 1

    def test_is_abbreviation_at(self):
        assert is_abbreviation_at("Look at Dr. Smith", 10) is True
        assert is_abbreviation_at("Look at Mr. Smith", 10) is True
        assert is_abbreviation_at("Here is car. Done", 11) is False


@pytest.mark.django_db
class TestSentenceExtraction:
    """Test suite for extracting containing sentences with accurate context offsets."""

    def test_extract_sentence_basic(self):
        body = "First sentence. Second sentence with target word here. Third sentence."
        # target word "target"
        char_start = body.index("target")
        char_end = char_start + len("target")

        sentence, ctx_start, ctx_end = extract_sentence_for_span(body, char_start, char_end)

        assert sentence == "Second sentence with target word here."
        assert sentence[ctx_start:ctx_end] == "target"

    def test_extract_phrase_context(self):
        body = "They arrived safe and sound after the long journey."
        phrase = "safe and sound"
        char_start = body.index(phrase)
        char_end = char_start + len(phrase)

        sentence, ctx_start, ctx_end = extract_sentence_for_span(body, char_start, char_end)

        assert sentence == "They arrived safe and sound after the long journey."
        assert sentence[ctx_start:ctx_end] == phrase

    def test_extract_long_sentence_windowing(self):
        # Create sentence > 400 characters
        prefix = "Word " * 60  # ~300 chars
        suffix = " more " * 60  # ~360 chars
        body = f"{prefix}TARGET{suffix}."

        char_start = body.index("TARGET")
        char_end = char_start + len("TARGET")

        sentence, ctx_start, ctx_end = extract_sentence_for_span(body, char_start, char_end)

        assert len(sentence) <= 400
        assert sentence[ctx_start:ctx_end] == "TARGET"
        assert sentence.startswith("… ") or sentence.endswith(" …")


@pytest.mark.django_db
class TestTextViewsAndAPI:
    """Test suite for text management views and cards creation API."""

    @pytest.fixture
    def user_a(self):
        return User.objects.create_user(username="usera@example.com", email="usera@example.com")

    @pytest.fixture
    def user_b(self):
        return User.objects.create_user(username="userb@example.com", email="userb@example.com")

    @pytest.fixture
    def client_a(self, user_a):
        c = Client()
        c.force_login(user_a)
        return c

    @pytest.fixture
    def text_a(self, user_a):
        return Text.objects.create(
            user=user_a,
            title="A Walk in the Woods",
            body="We walked through the dense forest. We felt safe and sound.",
        )

    def test_text_create_flow(self, client_a, user_a):
        # GET form
        res = client_a.get("/texts/new/")
        assert res.status_code == 200
        assert "ورود متن شبانه جدید" in res.content.decode("utf-8")

        # POST empty body -> error
        res_empty = client_a.post("/texts/new/", {"title": "Test", "body": ""})
        assert res_empty.status_code == 200
        assert "لطفاً متن انگلیسی را وارد کنید" in res_empty.content.decode("utf-8")

        # POST valid body -> creates text and redirects to select
        res_post = client_a.post(
            "/texts/new/",
            {"title": "Custom Title", "body": "Hello world from the forest.\r\nSecond line."},
        )
        assert res_post.status_code == 302
        new_text = Text.objects.get(user=user_a, title="Custom Title")
        assert "\r" not in new_text.body
        assert res_post.url == f"/texts/{new_text.id}/select/"

    def test_text_list_scoped_to_user(self, client_a, user_a, user_b, text_a):
        # Create text for user B
        Text.objects.create(user=user_b, title="User B Secret Text", body="Secret body.")

        res = client_a.get("/texts/")
        assert res.status_code == 200
        content = res.content.decode("utf-8")
        assert "A Walk in the Woods" in content
        assert "User B Secret Text" not in content

    def test_text_detail_view(self, client_a, text_a):
        res = client_a.get(f"/texts/{text_a.id}/")
        assert res.status_code == 200
        assert text_a.title in res.content.decode("utf-8")

    def test_text_select_view(self, client_a, text_a):
        res = client_a.get(f"/texts/{text_a.id}/select/")
        assert res.status_code == 200
        content = res.content.decode("utf-8")
        assert 'class="tok"' in content
        assert "dense" in content

    def test_save_single_card_and_phrase_card(self, client_a, text_a):
        # "forest" -> single word
        # "safe and sound" -> 3-token phrase
        forest_start = text_a.body.index("forest")
        forest_end = forest_start + len("forest")

        phrase_start = text_a.body.index("safe and sound")
        phrase_end = phrase_start + len("safe and sound")

        payload = {
            "cards": [
                {
                    "start": forest_start,
                    "end": forest_end,
                    "pos": "noun",
                    "meaning": "جنگل",
                },
                {
                    "start": phrase_start,
                    "end": phrase_end,
                    "pos": "idiom",
                    "meaning": "سالم و سلامت",
                },
            ]
        }

        res = client_a.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["saved_count"] == 2

        cards = WordCard.objects.filter(source_text=text_a).order_by("char_start")
        assert cards.count() == 2

        c1 = cards[0]
        assert c1.word == "forest"
        assert c1.pos == "noun"
        assert c1.meaning == "جنگل"
        assert c1.stage == 0
        assert c1.target_type == 1
        assert c1.context_sentence == "We walked through the dense forest."
        assert c1.context_sentence[c1.ctx_start : c1.ctx_end] == "forest"

        c2 = cards[1]
        assert c2.word == "safe and sound"
        assert c2.pos == "idiom"
        assert c2.meaning == "سالم و سلامت"
        assert c2.stage == 0
        assert c2.context_sentence == "We felt safe and sound."
        assert c2.context_sentence[c2.ctx_start : c2.ctx_end] == "safe and sound"

    def test_save_cards_rejects_more_than_5_words_in_phrase(self, client_a, text_a):
        # Adjust text to have a 6-word span
        text_a.body = "one two three four five six seven."
        text_a.save()

        start = text_a.body.index("one two three four five six")
        end = start + len("one two three four five six")

        payload = {
            "cards": [
                {"start": start, "end": end, "pos": "phrase", "meaning": "عبارت طولانی"}
            ]
        }
        res = client_a.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert res.status_code == 400
        assert "بیش از ۵ کلمه" in res.json()["error"]

    def test_save_cards_rejects_invalid_offsets_and_large_batches(self, client_a, text_a):
        # Negative start
        res1 = client_a.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps({"cards": [{"start": -1, "end": 5, "pos": "noun", "meaning": "test"}]}),
            content_type="application/json",
        )
        assert res1.status_code == 400

        # Start >= End
        res2 = client_a.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps({"cards": [{"start": 10, "end": 5, "pos": "noun", "meaning": "test"}]}),
            content_type="application/json",
        )
        assert res2.status_code == 400

        # More than 30 cards
        too_many = [
            {"start": 0, "end": 2, "pos": "noun", "meaning": f"w{i}"}
            for i in range(31)
        ]
        res3 = client_a.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps({"cards": too_many}),
            content_type="application/json",
        )
        assert res3.status_code == 400
        assert "حداکثر ۳۰ کلمه" in res3.json()["error"]

    def test_idor_protection(self, user_b, text_a):
        # User B cannot access or save cards to User A's text
        client_b = Client()
        client_b.force_login(user_b)

        # GET detail -> 404
        assert client_b.get(f"/texts/{text_a.id}/").status_code == 404

        # GET select -> 404
        assert client_b.get(f"/texts/{text_a.id}/select/").status_code == 404

        # POST cards -> 404
        res = client_b.post(
            f"/api/texts/{text_a.id}/cards/",
            data=json.dumps({"cards": [{"start": 0, "end": 2, "pos": "noun", "meaning": "x"}]}),
            content_type="application/json",
        )
        assert res.status_code == 404

    def test_text_body_read_only_when_cards_exist(self, user_a, text_a):
        # Create a card referencing text_a
        WordCard.objects.create(
            user=user_a,
            source_text=text_a,
            word="dense",
            lemma="dense",
            pos="adjective",
            meaning="متراکم",
            context_sentence="We walked through the dense forest.",
            ctx_start=22,
            ctx_end=27,
            char_start=22,
            char_end=27,
            stage=0,
            target_type=1,
        )

        # Attempting to change text body must raise ValidationError
        text_a.body = "Modified body completely."
        with pytest.raises(ValidationError) as exc:
            text_a.save()
        assert any("ویرایش" in m for m in exc.value.messages)
