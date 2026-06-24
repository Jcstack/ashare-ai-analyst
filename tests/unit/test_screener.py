"""Tests for StockScreener — multi-factor screening engine.

Part of v28.0 Smart Stock Recommendation System.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.recommendation.screener import StockScreener, _safe_float


@pytest.fixture(autouse=True)
def _no_screener_network():
    """Stub the screener's live-network boundaries for deterministic tests.

    ``StockScreener.screen`` touches the network in two places:
      * the recent-IPO exclusion calls ``_fetch_listing_dates`` →
        ``akshare.stock_info_a_code_name`` (live), and
      * candidate enrichment calls
        ``OvernightRiskCalculator.calculate_batch`` → live OHLCV fetch.
    Patch both so screening logic is exercised offline and deterministically
    (matching the graceful empty-result behaviour the screener already handles
    when these fetches fail).
    """
    with (
        patch.object(StockScreener, "_fetch_listing_dates", return_value={}),
        patch(
            "src.recommendation.overnight_risk.OvernightRiskCalculator.calculate_batch",
            return_value={},
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "styles": {
        "value": {
            "label": "价值投资",
            "filters": {"pe_max": 25, "pb_max": 3},
            "weights": {"pe_score": 0.4, "pb_score": 0.3, "stability": 0.3},
        },
        "momentum": {
            "label": "动量交易",
            "filters": {"change_pct_min": 1, "turnover_min": 3},
            "weights": {"price_momentum": 0.5, "volume_momentum": 0.3, "turnover": 0.2},
        },
    },
    "screening": {
        "max_candidates_per_style": 5,
        "min_score": 0.3,
    },
}

SAMPLE_MARKET_DATA = [
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "price": 1800.0,
        "change_pct": 0.5,
        "volume": 50000,
        "turnover_rate": 0.3,
        "pe_ratio": 20.0,
        "pb_ratio": 2.5,
        "market_cap": 2e12,
        "sector": "白酒",
        "volume_ratio": 1.2,
    },
    {
        "symbol": "000858",
        "name": "五粮液",
        "price": 150.0,
        "change_pct": -0.3,
        "volume": 80000,
        "turnover_rate": 1.0,
        "pe_ratio": 18.0,
        "pb_ratio": 2.0,
        "market_cap": 5e11,
        "sector": "白酒",
        "volume_ratio": 1.0,
    },
    {
        "symbol": "300750",
        "name": "宁德时代",
        "price": 200.0,
        "change_pct": 3.0,
        "volume": 200000,
        "turnover_rate": 5.0,
        "pe_ratio": 35.0,
        "pb_ratio": 5.0,
        "market_cap": 8e11,
        "sector": "电力设备",
        "volume_ratio": 2.5,
    },
    {
        "symbol": "601318",
        "name": "中国平安",
        "price": 50.0,
        "change_pct": 2.0,
        "volume": 300000,
        "turnover_rate": 4.0,
        "pe_ratio": 10.0,
        "pb_ratio": 1.2,
        "market_cap": 9e11,
        "sector": "保险",
        "volume_ratio": 1.8,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStockScreener:
    """Tests for StockScreener operations."""

    @pytest.fixture()
    def screener(self) -> StockScreener:
        return StockScreener(SAMPLE_CONFIG)

    def test_screen_value_style(self, screener: StockScreener) -> None:
        """Value style should filter out high PE/PB stocks."""
        candidates = screener.screen("value", SAMPLE_MARKET_DATA)
        # 宁德时代 PE=35 > 25, PB=5 > 3, should be filtered
        symbols = [c.symbol for c in candidates]
        assert "300750" not in symbols
        assert len(candidates) > 0

    def test_screen_momentum_style(self, screener: StockScreener) -> None:
        """Momentum style should require change_pct >= 1 and turnover >= 3."""
        candidates = screener.screen("momentum", SAMPLE_MARKET_DATA)
        # 贵州茅台 change=0.5 < 1, 五粮液 change=-0.3, both filtered
        for c in candidates:
            assert c.change_pct >= 1
            assert c.turnover_rate >= 3

    def test_screen_unknown_style(self, screener: StockScreener) -> None:
        """Unknown style returns empty list."""
        candidates = screener.screen("nonexistent", SAMPLE_MARKET_DATA)
        assert candidates == []

    def test_screen_empty_data(self, screener: StockScreener) -> None:
        """Empty market data returns empty list."""
        candidates = screener.screen("value", [])
        assert candidates == []

    def test_candidates_have_scores(self, screener: StockScreener) -> None:
        """All candidates should have computed scores."""
        candidates = screener.screen("value", SAMPLE_MARKET_DATA)
        for c in candidates:
            assert 0 <= c.score <= 1
            assert isinstance(c.factors, dict)
            assert len(c.factors) > 0

    def test_candidates_sorted_by_score(self, screener: StockScreener) -> None:
        """Candidates should be sorted by score descending."""
        candidates = screener.screen("value", SAMPLE_MARKET_DATA)
        if len(candidates) > 1:
            for i in range(len(candidates) - 1):
                assert candidates[i].score >= candidates[i + 1].score

    def test_max_candidates_limit(self, screener: StockScreener) -> None:
        """Should not exceed max_candidates_per_style."""
        # Make a big dataset
        big_data = []
        for i in range(50):
            big_data.append(
                {
                    "symbol": f"{600000 + i}",
                    "name": f"测试股{i}",
                    "price": 10.0 + i,
                    "change_pct": 0.1 * i,
                    "volume": 100000,
                    "turnover_rate": 1.0,
                    "pe_ratio": 10.0 + i * 0.2,
                    "pb_ratio": 1.0 + i * 0.03,
                    "market_cap": 1e10,
                    "sector": "测试",
                    "volume_ratio": 1.0,
                }
            )
        candidates = screener.screen("value", big_data)
        assert len(candidates) <= 5  # max_candidates_per_style

    def test_candidate_fields(self, screener: StockScreener) -> None:
        """Candidate should have all required fields populated."""
        candidates = screener.screen("value", SAMPLE_MARKET_DATA)
        if candidates:
            c = candidates[0]
            assert c.symbol
            assert c.name
            assert c.price > 0
            assert isinstance(c.pe_ratio, (float, type(None)))
            assert c.sector

    def test_blacklist_exclusion(self, screener: StockScreener) -> None:
        """Blacklisted symbols should be excluded from screening."""
        candidates = screener.screen(
            "value", SAMPLE_MARKET_DATA, blacklist={"600519", "000858"}
        )
        symbols = [c.symbol for c in candidates]
        assert "600519" not in symbols
        assert "000858" not in symbols

    def test_blacklist_empty(self, screener: StockScreener) -> None:
        """Empty blacklist should not affect results."""
        without = screener.screen("value", SAMPLE_MARKET_DATA)
        with_empty = screener.screen("value", SAMPLE_MARKET_DATA, blacklist=set())
        assert len(without) == len(with_empty)


class TestSectorPreferences:
    """Tests for sector preference boost + anti-filter-bubble."""

    def test_no_preferences(self) -> None:
        """No sector preferences returns candidates unchanged."""
        from src.recommendation.models import StockCandidate

        candidates = [
            StockCandidate(
                symbol="600519",
                name="贵州茅台",
                price=1800,
                change_pct=0.5,
                volume=50000,
                turnover_rate=0.3,
                pe_ratio=20,
                pb_ratio=2.5,
                market_cap=2e12,
                sector="白酒",
                score=0.85,
                factors={},
            ),
        ]
        result = StockScreener.apply_sector_preferences(candidates, [])
        assert len(result) == len(candidates)

    def test_preferred_sector_boost(self) -> None:
        """Preferred sectors should get more slots."""
        from src.recommendation.models import StockCandidate

        candidates = []
        for i in range(10):
            sector = "白酒" if i < 6 else "电力设备"
            candidates.append(
                StockCandidate(
                    symbol=f"60{i:04d}",
                    name=f"测试{i}",
                    price=100,
                    change_pct=1,
                    volume=10000,
                    turnover_rate=2,
                    pe_ratio=15,
                    pb_ratio=2,
                    market_cap=1e10,
                    sector=sector,
                    score=0.8 - i * 0.01,
                    factors={},
                )
            )

        result = StockScreener.apply_sector_preferences(candidates, ["白酒"])
        assert len(result) == 10
        # At least 20% should be non-preferred (cross-sector)
        cross_sector = [c for c in result if c.sector != "白酒"]
        assert len(cross_sector) >= 2  # ceil(10 * 0.2) = 2

    def test_cross_sector_tagged(self) -> None:
        """Non-preferred sector items should be tagged."""
        from src.recommendation.models import StockCandidate

        candidates = [
            StockCandidate(
                symbol="600519",
                name="贵州茅台",
                price=1800,
                change_pct=0.5,
                volume=50000,
                turnover_rate=0.3,
                pe_ratio=20,
                pb_ratio=2.5,
                market_cap=2e12,
                sector="白酒",
                score=0.85,
                factors={},
            ),
            StockCandidate(
                symbol="300750",
                name="宁德时代",
                price=200,
                change_pct=3,
                volume=200000,
                turnover_rate=5,
                pe_ratio=35,
                pb_ratio=5,
                market_cap=8e11,
                sector="电力设备",
                score=0.8,
                factors={},
            ),
        ]
        result = StockScreener.apply_sector_preferences(candidates, ["白酒"])
        non_pref = [c for c in result if c.sector != "白酒"]
        for c in non_pref:
            assert c.factors.get("cross_sector_discovery") == 1.0


class TestSectorCap:
    """Tests for per-sector cap to prevent single-sector dominance."""

    @pytest.fixture()
    def screener(self) -> StockScreener:
        config = {
            "styles": {
                "value": {
                    "label": "价值投资",
                    "filters": {"pe_max": 25, "pb_max": 3},
                    "weights": {"pe_score": 0.4, "pb_score": 0.3, "stability": 0.3},
                },
            },
            "screening": {
                "max_candidates_per_style": 10,
                "min_score": 0.3,
                "max_per_sector": 2,
            },
        }
        return StockScreener(config)

    def test_sector_cap_limits_same_sector(self, screener: StockScreener) -> None:
        """No more than max_per_sector candidates from the same sector."""
        data = []
        for i in range(10):
            data.append(
                {
                    "symbol": f"60{i:04d}",
                    "name": f"银行{i}",
                    "price": 10.0 + i,
                    "change_pct": 0.5,
                    "volume": 100000,
                    "turnover_rate": 1.0,
                    "pe_ratio": 5.0 + i * 0.1,
                    "pb_ratio": 0.6,
                    "market_cap": 1e11,
                    "sector": "银行",
                    "volume_ratio": 1.0,
                }
            )
        candidates = screener.screen("value", data)
        bank_count = sum(1 for c in candidates if c.sector == "银行")
        # With max_per_sector=2, the first 2 slots go to banks, rest are backfill
        assert bank_count <= 2

    def test_sector_cap_allows_diversity(self, screener: StockScreener) -> None:
        """Multiple sectors should each get up to max_per_sector slots."""
        data = []
        sectors = [
            "银行",
            "银行",
            "银行",
            "银行",
            "白酒",
            "白酒",
            "白酒",
            "保险",
            "保险",
            "电力设备",
        ]
        for i, sector in enumerate(sectors):
            data.append(
                {
                    "symbol": f"60{i:04d}",
                    "name": f"测试{i}",
                    "price": 10.0,
                    "change_pct": 0.5,
                    "volume": 100000,
                    "turnover_rate": 1.0,
                    "pe_ratio": 8.0 + i * 0.5,
                    "pb_ratio": 1.0,
                    "market_cap": 1e10,
                    "sector": sector,
                    "volume_ratio": 1.0,
                }
            )
        candidates = screener.screen("value", data)
        from collections import Counter

        sector_counts = Counter(c.sector for c in candidates)
        for sector, count in sector_counts.items():
            assert count <= 2, f"{sector} has {count} candidates, expected <= 2"
        # Should have multiple sectors represented
        assert len(sector_counts) >= 2

    def test_static_sector_cap(self) -> None:
        """_apply_sector_cap static behavior."""
        from src.recommendation.models import StockCandidate

        candidates = []
        for i in range(6):
            candidates.append(
                StockCandidate(
                    symbol=f"60{i:04d}",
                    name=f"测试{i}",
                    price=10.0,
                    change_pct=0.5,
                    volume=100000,
                    turnover_rate=1.0,
                    pe_ratio=10.0,
                    pb_ratio=1.0,
                    market_cap=1e10,
                    sector="银行" if i < 4 else "保险",
                    score=0.9 - i * 0.05,
                    factors={},
                )
            )
        result = StockScreener._apply_sector_cap(candidates, max_per_sector=2)
        # 2 银行 + 2 保险 = 4 total (excess 银行 dropped)
        assert len(result) == 4
        bank_count = sum(1 for c in result if c.sector == "银行")
        insurance_count = sum(1 for c in result if c.sector == "保险")
        assert bank_count == 2
        assert insurance_count == 2


class TestExchangeExclusion:
    """Tests for configurable exchange exclusion (I-062)."""

    def _make_stock(self, symbol: str, name: str = "测试") -> dict:
        return {
            "symbol": symbol,
            "name": name,
            "price": 10.0,
            "change_pct": 0.5,
            "volume": 100000,
            "turnover_rate": 1.0,
            "pe_ratio": 10.0,
            "pb_ratio": 1.0,
            "market_cap": 1e10,
            "sector": "测试",
            "volume_ratio": 1.0,
        }

    def test_bse_excluded_by_default_config(self) -> None:
        """BSE stocks (83/87/43/92/8 prefixes) excluded when exclude_exchanges=['bse']."""
        config = {
            "styles": SAMPLE_CONFIG["styles"],
            "screening": {**SAMPLE_CONFIG["screening"], "exclude_exchanges": ["bse"]},
        }
        screener = StockScreener(config)
        data = [
            self._make_stock("600519"),  # 沪市 — keep
            self._make_stock("830001"),  # 北交所 — exclude
            self._make_stock("870001"),  # 北交所 — exclude
            self._make_stock("430001"),  # 北交所 — exclude
            self._make_stock("920662"),  # 北交所 920xxx — exclude
            self._make_stock("000858"),  # 深市 — keep
        ]
        candidates = screener.screen("value", data)
        symbols = {c.symbol for c in candidates}
        assert "600519" in symbols
        assert "000858" in symbols
        assert "830001" not in symbols
        assert "870001" not in symbols
        assert "430001" not in symbols
        assert "920662" not in symbols

    def test_bse_excluded_with_exchange_prefix(self) -> None:
        """BSE stocks with bj/sh/sz prefix are also caught after stripping."""
        config = {
            "styles": SAMPLE_CONFIG["styles"],
            "screening": {**SAMPLE_CONFIG["screening"], "exclude_exchanges": ["bse"]},
        }
        screener = StockScreener(config)
        data = [
            self._make_stock("sh600519"),  # 沪市 with prefix — keep
            self._make_stock("bj920370"),  # 北交所 with prefix — exclude
            self._make_stock("bj830001"),  # 北交所 with prefix — exclude
            self._make_stock("sz000858"),  # 深市 with prefix — keep
        ]
        candidates = screener.screen("value", data)
        symbols = {c.symbol for c in candidates}
        assert "sh600519" in symbols
        assert "sz000858" in symbols
        assert "bj920370" not in symbols
        assert "bj830001" not in symbols

    def test_no_exclusion_when_empty(self) -> None:
        """No stocks excluded when exclude_exchanges is empty."""
        config = {
            "styles": SAMPLE_CONFIG["styles"],
            "screening": {**SAMPLE_CONFIG["screening"], "exclude_exchanges": []},
        }
        screener = StockScreener(config)
        data = [
            self._make_stock("600519"),
            self._make_stock("830001"),
        ]
        candidates = screener.screen("value", data)
        symbols = {c.symbol for c in candidates}
        assert "830001" in symbols

    def test_build_excluded_prefixes(self) -> None:
        """_build_excluded_prefixes maps exchange names to prefix tuples."""
        assert StockScreener._build_excluded_prefixes(["bse"]) == (
            "83",
            "87",
            "43",
            "92",
            "8",
        )
        assert StockScreener._build_excluded_prefixes(["star"]) == ("688", "689")
        assert StockScreener._build_excluded_prefixes([]) == ()


class TestDataQuality:
    """Tests for data_quality factor and score cap (I-067)."""

    @pytest.fixture()
    def screener(self) -> StockScreener:
        return StockScreener(SAMPLE_CONFIG)

    def test_full_data_quality_high(self, screener: StockScreener) -> None:
        """Stock with all fields present gets data_quality = 1.0."""
        stock = {
            "symbol": "600519",
            "name": "贵州茅台",
            "price": 1800.0,
            "change_pct": 0.5,
            "volume": 50000,
            "turnover_rate": 0.3,
            "pe_ratio": 20.0,
            "pb_ratio": 2.5,
            "market_cap": 2e12,
            "sector": "白酒",
            "volume_ratio": 1.2,
        }
        factors = screener._compute_factors("value", stock)
        assert factors["data_quality"] == 1.0

    def test_sina_data_quality_low(self, screener: StockScreener) -> None:
        """Sina-style stock (no PE/PB/sector/turnover/volume_ratio) gets low data_quality."""
        stock = {
            "symbol": "600519",
            "name": "贵州茅台",
            "price": 1800.0,
            "change_pct": 5.0,
            "volume": 50000,
            "turnover_rate": None,
            "pe_ratio": None,
            "pb_ratio": None,
            "market_cap": None,
            "sector": "",
            "volume_ratio": None,
        }
        factors = screener._compute_factors("value", stock)
        # 0 of 6 key fields present → data_quality = 0.0
        assert factors["data_quality"] == 0.0

    def test_partial_data_quality(self, screener: StockScreener) -> None:
        """Stock with some fields gets proportional data_quality."""
        stock = {
            "symbol": "600519",
            "name": "贵州茅台",
            "price": 1800.0,
            "change_pct": 3.0,
            "volume": 50000,
            "turnover_rate": 2.0,
            "pe_ratio": 15.0,
            "pb_ratio": None,
            "market_cap": None,
            "sector": "",
            "volume_ratio": None,
        }
        factors = screener._compute_factors("value", stock)
        # pe + turnover = 2/6 ≈ 0.3333
        assert 0.3 <= factors["data_quality"] <= 0.4

    def test_score_cap_for_low_quality(self) -> None:
        """Stocks with data_quality < 0.2 should have score capped at 0.7."""
        config = {
            "styles": {
                "momentum": {
                    "label": "动量",
                    "filters": {},
                    "weights": {"price_momentum": 0.5, "trend": 0.5},
                },
            },
            "screening": {"max_candidates_per_style": 10, "min_score": 0.3},
        }
        screener = StockScreener(config)
        # Sina-like stock with strong (but not limit-up) momentum: uncapped it would
        # score ~0.8, so the data_quality cap to 0.7 is what's exercised here.
        # (A ~limit-up change_pct would instead be removed by the T+1 drift filter.)
        data = [
            {
                "symbol": "600001",
                "name": "测试",
                "price": 10.0,
                "change_pct": 5.0,
                "volume": 100000,
                "turnover_rate": None,
                "pe_ratio": None,
                "pb_ratio": None,
                "market_cap": None,
                "sector": "",
                "volume_ratio": None,
            },
        ]
        # Mock the live akshare listing-date lookup so the test is deterministic
        # and network-free (otherwise the recent-IPO filter depends on a real fetch).
        with patch.object(screener, "_fetch_listing_dates", return_value={}):
            candidates = screener.screen("momentum", data)
        assert len(candidates) == 1
        # Score should be capped at 0.7 due to data_quality < 0.2
        assert candidates[0].score <= 0.7

    def test_volume_defaults_below_neutral(self, screener: StockScreener) -> None:
        """None volume fields should default to 0.35, not 0.5."""
        stock = {
            "symbol": "600519",
            "name": "贵州茅台",
            "price": 1800.0,
            "change_pct": 0.5,
            "volume": 50000,
            "turnover_rate": None,
            "pe_ratio": 20.0,
            "pb_ratio": 2.5,
            "market_cap": 2e12,
            "sector": "白酒",
            "volume_ratio": None,
        }
        factors = screener._compute_factors("value", stock)
        assert factors["volume_momentum"] == 0.35
        assert factors["turnover"] == 0.35
        assert factors["volume_pattern"] == 0.35
        assert factors["flow_score"] == 0.35


class TestFactorSymmetry:
    """Tests for factor formula symmetry around 0.5 (I-049 Layer 3)."""

    @pytest.fixture()
    def screener(self) -> StockScreener:
        return StockScreener(SAMPLE_CONFIG)

    def _factors_for_change(self, screener: StockScreener, change_pct: float) -> dict:
        stock = {
            "symbol": "600519",
            "name": "Test",
            "price": 100.0,
            "change_pct": change_pct,
            "volume": 100000,
            "turnover_rate": 2.0,
            "pe_ratio": 15.0,
            "pb_ratio": 2.0,
            "market_cap": 1e10,
            "sector": "测试",
            "volume_ratio": 1.0,
        }
        return screener._compute_factors("value", stock)

    def test_zero_change_produces_half(self, screener: StockScreener) -> None:
        """0% change → price_momentum=0.5, trend=0.5."""
        f = self._factors_for_change(screener, 0.0)
        assert f["price_momentum"] == 0.5
        assert f["trend"] == 0.5

    def test_negative_change_below_half(self, screener: StockScreener) -> None:
        """Negative change → factors below 0.5."""
        f = self._factors_for_change(screener, -2.0)
        assert f["price_momentum"] < 0.5
        assert f["trend"] < 0.5

    def test_symmetric_distance(self, screener: StockScreener) -> None:
        """+3% and -3% should be equidistant from 0.5."""
        f_pos = self._factors_for_change(screener, 3.0)
        f_neg = self._factors_for_change(screener, -3.0)
        # price_momentum: 0.5 + 3/20 = 0.65 vs 0.5 - 3/20 = 0.35
        assert (
            abs((f_pos["price_momentum"] - 0.5) - (0.5 - f_neg["price_momentum"]))
            < 0.001
        )
        assert abs((f_pos["trend"] - 0.5) - (0.5 - f_neg["trend"])) < 0.001


class TestSafeFloat:
    """Tests for _safe_float helper."""

    def test_normal(self) -> None:
        assert _safe_float(3.14) == 3.14

    def test_string(self) -> None:
        assert _safe_float("42.5") == 42.5

    def test_none(self) -> None:
        assert _safe_float(None) is None

    def test_invalid(self) -> None:
        assert _safe_float("abc") is None

    def test_nan(self) -> None:
        assert _safe_float(float("nan")) is None
