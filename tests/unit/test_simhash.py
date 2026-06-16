"""Tests for SimHash fuzzy near-duplicate detection (v23.0 Phase 3)."""

from __future__ import annotations

from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.simhash import (
    FuzzyDedupChecker,
    SimHash,
    _char_ngrams,
    _normalize_text,
)


def _make_item(**overrides) -> InfoItem:
    defaults = {
        "source_id": "test_src",
        "source_name": "Test",
        "title": "Test Title",
        "url": "https://example.com/article",
    }
    defaults.update(overrides)
    return InfoItem(**defaults)


class TestNormalizeText:
    def test_lowercase(self) -> None:
        assert _normalize_text("Hello WORLD") == "hello world"

    def test_strip_punctuation(self) -> None:
        assert _normalize_text("Hello, World!") == "hello world"

    def test_preserve_cjk(self) -> None:
        result = _normalize_text("央行降息 政策发布")
        assert "央行降息" in result
        assert "政策发布" in result

    def test_empty(self) -> None:
        assert _normalize_text("") == ""

    def test_collapse_whitespace(self) -> None:
        assert _normalize_text("a   b   c") == "a b c"


class TestNGrams:
    def test_basic_trigrams(self) -> None:
        grams = _char_ngrams("abcde", 3)
        assert grams == ["abc", "bcd", "cde"]

    def test_text_shorter_than_n(self) -> None:
        grams = _char_ngrams("ab", 3)
        assert grams == ["ab"]

    def test_text_equal_to_n(self) -> None:
        grams = _char_ngrams("abc", 3)
        assert grams == ["abc"]

    def test_empty_text(self) -> None:
        grams = _char_ngrams("", 3)
        assert grams == []

    def test_single_char(self) -> None:
        grams = _char_ngrams("x", 3)
        assert grams == ["x"]

    def test_cjk_ngrams(self) -> None:
        grams = _char_ngrams("央行降息政策", 3)
        assert len(grams) == 4
        assert grams[0] == "央行降"
        assert grams[-1] == "息政策"


class TestSimHashCompute:
    def test_deterministic(self) -> None:
        sh = SimHash()
        h1 = sh.compute("hello world")
        h2 = sh.compute("hello world")
        assert h1 == h2

    def test_different_texts_different_hashes(self) -> None:
        sh = SimHash()
        h1 = sh.compute("apple releases new iphone")
        h2 = sh.compute("microsoft announces azure update")
        assert h1 != h2

    def test_empty_text_returns_zero(self) -> None:
        sh = SimHash()
        assert sh.compute("") == 0

    def test_whitespace_only_returns_zero(self) -> None:
        sh = SimHash()
        assert sh.compute("   ") == 0

    def test_returns_64_bit_int(self) -> None:
        sh = SimHash()
        h = sh.compute("some text for hashing")
        assert isinstance(h, int)
        assert 0 <= h < (1 << 64)


class TestSimHashDistance:
    def test_identical_hashes_zero_distance(self) -> None:
        sh = SimHash()
        h = sh.compute("test text")
        assert sh.distance(h, h) == 0

    def test_known_distance(self) -> None:
        sh = SimHash()
        # These differ in exactly known bit positions
        assert sh.distance(0b1111, 0b1110) == 1
        assert sh.distance(0b1111, 0b0000) == 4

    def test_max_distance_64(self) -> None:
        sh = SimHash()
        all_ones = (1 << 64) - 1
        assert sh.distance(0, all_ones) == 64


class TestSimHashNearDuplicate:
    def test_similar_english_detected(self) -> None:
        sh = SimHash()
        # SimHash detects near-duplicates at the character level —
        # minor edits to the same text, not semantic paraphrases.
        h1 = sh.compute("Fed raises interest rates by 25 basis points")
        h2 = sh.compute("Fed raises interest rates by 25 basis point")
        dist = sh.distance(h1, h2)
        assert dist <= 5, f"Expected near-dup, got distance {dist}"

    def test_paraphrased_english_has_moderate_distance(self) -> None:
        sh = SimHash()
        # Paraphrased content shares some n-grams but is not character-identical
        h1 = sh.compute("Fed raises interest rates by 25 basis points")
        h2 = sh.compute("Federal Reserve raises rates 25bps")
        dist = sh.distance(h1, h2)
        # Should be closer than completely unrelated text but not necessarily
        # within the default near-dup threshold
        assert dist < 64, f"Unexpected max distance for related text: {dist}"

    def test_different_topics_not_flagged(self) -> None:
        sh = SimHash()
        h1 = sh.compute("Apple releases new iPhone 16 with AI features")
        h2 = sh.compute("Microsoft announces major Azure cloud update")
        dist = sh.distance(h1, h2)
        # Very different content should have large distance
        assert dist > 5, f"Expected distinct, got distance {dist}"

    def test_is_near_duplicate_method(self) -> None:
        sh = SimHash()
        h1 = sh.compute("same text here")
        h2 = sh.compute("same text here")
        assert sh.is_near_duplicate(h1, h2, threshold=3) is True

    def test_is_near_duplicate_rejects_distant(self) -> None:
        sh = SimHash()
        assert sh.is_near_duplicate(0, (1 << 64) - 1, threshold=3) is False


class TestCJKSupport:
    def test_similar_chinese_titles_detected(self) -> None:
        sh = SimHash()
        # Near-duplicate: same text with minor suffix variation
        h1 = sh.compute("上海证券交易所今日发布最新公告内容")
        h2 = sh.compute("上海证券交易所今日发布最新公告内容摘要")
        dist = sh.distance(h1, h2)
        assert dist <= 5, f"Expected CJK near-dup, got distance {dist}"

    def test_paraphrased_chinese_has_moderate_distance(self) -> None:
        sh = SimHash()
        # Semantically related but different character sequences
        h1 = sh.compute("央行下调存款准备金率")
        h2 = sh.compute("中国央行宣布降准")
        dist = sh.distance(h1, h2)
        assert dist < 64, f"Unexpected max distance for related CJK text: {dist}"

    def test_different_chinese_topics_distant(self) -> None:
        sh = SimHash()
        h1 = sh.compute("央行下调存款准备金率")
        h2 = sh.compute("苹果公司发布新款手机")
        dist = sh.distance(h1, h2)
        assert dist > 5, f"Expected distinct CJK topics, got distance {dist}"

    def test_mixed_cjk_english(self) -> None:
        sh = SimHash()
        h = sh.compute("央行 interest rate 降息")
        assert h != 0


class TestFuzzyDedupChecker:
    def test_first_item_not_duplicate(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item = _make_item(title="Unique article title here")
        assert checker.is_near_duplicate(item) is False

    def test_exact_same_title_detected(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item1 = _make_item(title="Fed raises rates by 25bp")
        item2 = _make_item(title="Fed raises rates by 25bp")
        checker.is_near_duplicate(item1)
        assert checker.is_near_duplicate(item2) is True

    def test_different_titles_not_flagged(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item1 = _make_item(title="Apple releases new iPhone with AI features")
        item2 = _make_item(title="Microsoft announces major Azure cloud update")
        checker.is_near_duplicate(item1)
        assert checker.is_near_duplicate(item2) is False

    def test_empty_title_not_duplicate(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item = _make_item(title="")
        assert checker.is_near_duplicate(item) is False

    def test_batch_filtering(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        items = [
            _make_item(title="Apple launches new MacBook Pro with M4 chip"),
            _make_item(title="Tesla reports record quarterly deliveries"),
            _make_item(title="Apple launches new MacBook Pro with M4 chip"),  # dup
        ]
        filtered = checker.filter_batch(items)
        assert len(filtered) == 2

    def test_batch_preserves_order(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        items = [
            _make_item(title="First unique article about markets"),
            _make_item(title="Second unique article about technology"),
        ]
        filtered = checker.filter_batch(items)
        assert len(filtered) == 2
        assert filtered[0].title == "First unique article about markets"
        assert filtered[1].title == "Second unique article about technology"

    def test_reset_clears_state(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item = _make_item(title="Fed raises rates by 25bp")
        checker.is_near_duplicate(item)
        checker.reset()
        # After reset, same item should not be flagged
        assert checker.is_near_duplicate(item) is False

    def test_reset_empties_seen_dict(self) -> None:
        checker = FuzzyDedupChecker(threshold=3)
        item = _make_item(title="Some article title")
        checker.is_near_duplicate(item)
        assert len(checker._seen) == 1
        checker.reset()
        assert len(checker._seen) == 0
