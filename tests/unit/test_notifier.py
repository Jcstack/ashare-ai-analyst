"""Unit tests for src/utils/notifier.py — DiscordNotifier.

Tests cover:
  - Successful notification sending (analysis alerts, daily summaries, errors)
  - Disabled notifications (no HTTP calls made)
  - Retry behavior on 5xx errors
  - No retry on 4xx errors
  - Missing webhook URL handling
  - Connection error graceful handling
  - Embed structure and color validation
"""

import pytest
from unittest.mock import MagicMock, patch

import requests


# Sample prediction dict used across tests
SAMPLE_PREDICTION = {
    "symbol": "000001",
    "trend": "bullish",
    "signal": "buy",
    "confidence": 0.75,
    "risk_level": "medium",
    "reasoning": ["技术面看好", "MACD金叉", "成交量放大", "突破阻力位"],
    "target_price_range": {"low": 10.5, "high": 11.2},
    "key_factors": ["均线多头排列", "资金流入"],
    "risk_warnings": ["短期涨幅过大", "注意回调风险"],
}

# Sample notification config matching config/notification.yaml
SAMPLE_NOTIFICATION_CONFIG = {
    "discord": {
        "enabled": True,
        "timeout_seconds": 10,
        "max_retries": 3,
        "retry_delay_seconds": 0,  # Zero delay for fast tests
        "templates": {
            "analysis_alert": {
                "color": 3447003,
                "title_template": "{symbol} — AI分析预警",
            },
            "daily_summary": {
                "color": 5763719,
                "title_template": "每日分析摘要 — {date}",
            },
            "error_alert": {
                "color": 15548997,
                "title_template": "系统错误告警",
            },
        },
    }
}


@pytest.fixture
def mock_config():
    """Patch load_config to return the sample notification config."""
    with patch("src.utils.notifier.load_config") as mock_load:
        mock_load.return_value = SAMPLE_NOTIFICATION_CONFIG
        yield mock_load


@pytest.fixture
def mock_webhook_url(monkeypatch):
    """Set a fake DISCORD_WEBHOOK_URL environment variable."""
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/12345678901234567/ABCDefgh1234567890_abcdefghijklmnop",
    )


@pytest.fixture
def notifier(mock_config, mock_webhook_url):
    """Create a DiscordNotifier with mocked config and webhook URL."""
    from src.utils.notifier import DiscordNotifier

    return DiscordNotifier()


class TestSendAnalysisAlert:
    """Tests for DiscordNotifier.send_analysis_alert()."""

    @patch("src.utils.notifier.requests.post")
    def test_send_analysis_alert_success(self, mock_post, notifier):
        """Verify successful analysis alert returns True on HTTP 204.

        Mocks requests.post to return 204, verifies the method returns
        True and that the webhook was called exactly once with the
        correct URL.
        """
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        result = notifier.send_analysis_alert("000001", SAMPLE_PREDICTION)

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "discord.com/api/webhooks" in call_kwargs.args[0]
        payload = call_kwargs.kwargs["json"]
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

        embed = payload["embeds"][0]
        assert "000001" in embed["title"]
        assert embed["color"] == 3447003

        # Verify fields contain expected data
        field_names = [f["name"] for f in embed["fields"]]
        assert "趋势" in field_names
        assert "信号" in field_names
        assert "置信度" in field_names
        assert "风险等级" in field_names
        assert "目标价格区间" in field_names
        assert "关键推理" in field_names
        assert "关键因素" in field_names
        assert "风险提示" in field_names

    @patch("src.utils.notifier.requests.post")
    def test_send_analysis_alert_disabled(
        self, mock_post, mock_config, mock_webhook_url
    ):
        """Verify no HTTP call is made when notifications are disabled.

        Sets enabled=False in config, verifies requests.post is never
        called and the method returns False.
        """
        disabled_config = {
            "discord": {
                **SAMPLE_NOTIFICATION_CONFIG["discord"],
                "enabled": False,
            }
        }
        mock_config.return_value = disabled_config

        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()
        result = notifier.send_analysis_alert("000001", SAMPLE_PREDICTION)

        assert result is False
        mock_post.assert_not_called()


class TestSendDailySummary:
    """Tests for DiscordNotifier.send_daily_summary()."""

    @patch("src.utils.notifier.requests.post")
    def test_send_daily_summary_formats_correctly(self, mock_post, notifier):
        """Verify daily summary embed contains all stock results.

        Passes multiple stock results and verifies each appears as a
        field in the embed with the correct signal and confidence format.
        """
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        results = [
            {"symbol": "000001", "signal": "buy", "confidence": 0.75},
            {"symbol": "600519", "signal": "hold", "confidence": 0.60},
            {"symbol": "300750", "signal": "sell", "confidence": 0.85},
        ]

        result = notifier.send_daily_summary(results)

        assert result is True
        mock_post.assert_called_once()

        payload = mock_post.call_args.kwargs["json"]
        embed = payload["embeds"][0]

        # Verify green color from config
        assert embed["color"] == 5763719
        assert "每日分析摘要" in embed["title"]
        assert "共分析 3 只股票" in embed["description"]

        # Verify each stock appears as a field
        field_names = [f["name"] for f in embed["fields"]]
        assert "000001" in field_names
        assert "600519" in field_names
        assert "300750" in field_names

        # Verify field values contain signal and confidence
        for field in embed["fields"]:
            assert "信号:" in field["value"]
            assert "置信度:" in field["value"]
            assert field["inline"] is True


class TestSendErrorAlert:
    """Tests for DiscordNotifier.send_error_alert()."""

    @patch("src.utils.notifier.requests.post")
    def test_send_error_alert_uses_red_color(self, mock_post, notifier):
        """Verify error alert uses the red color from config.

        Sends an error alert and checks the embed color matches the
        configured error_alert color (15548997 = red).
        """
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        result = notifier.send_error_alert("数据库连接失败")

        assert result is True
        mock_post.assert_called_once()

        payload = mock_post.call_args.kwargs["json"]
        embed = payload["embeds"][0]

        assert embed["color"] == 15548997
        assert embed["title"] == "系统错误告警"

        # Verify error message appears in fields
        error_field = next(f for f in embed["fields"] if f["name"] == "错误信息")
        assert error_field["value"] == "数据库连接失败"

        # Verify timestamp field exists
        time_field = next(f for f in embed["fields"] if f["name"] == "发生时间")
        assert time_field["value"]  # Non-empty timestamp


class TestPostWebhook:
    """Tests for DiscordNotifier._post_webhook() retry and error logic."""

    @patch("src.utils.notifier.requests.post")
    def test_post_webhook_retries_on_5xx(self, mock_post, notifier):
        """Verify retry behavior on 5xx server errors.

        Mocks requests.post to return 500 on first call, then 204 on
        the second call. Verifies the method retries and ultimately
        returns True.
        """
        response_500 = MagicMock()
        response_500.status_code = 500

        response_204 = MagicMock()
        response_204.status_code = 204

        mock_post.side_effect = [response_500, response_204]

        result = notifier._post_webhook({"embeds": []})

        assert result is True
        assert mock_post.call_count == 2

    @patch("src.utils.notifier.requests.post")
    def test_post_webhook_no_retry_on_4xx(self, mock_post, notifier):
        """Verify no retry on 4xx client errors.

        Mocks requests.post to return 400. Verifies the method returns
        False immediately without retrying.
        """
        response_400 = MagicMock()
        response_400.status_code = 400
        response_400.text = "Bad Request"
        mock_post.return_value = response_400

        result = notifier._post_webhook({"embeds": []})

        assert result is False
        mock_post.assert_called_once()

    @patch("src.utils.notifier.requests.post")
    def test_missing_webhook_url_returns_false(
        self, mock_post, mock_config, monkeypatch
    ):
        """Verify False is returned when webhook URL is not set.

        Does not set DISCORD_WEBHOOK_URL env var, creating a notifier
        with an empty webhook URL. Verifies _post_webhook returns False
        and no HTTP call is made.
        """
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()

        result = notifier._post_webhook({"embeds": []})

        assert result is False
        mock_post.assert_not_called()

    @patch("src.utils.notifier.requests.post")
    def test_connection_error_handled(self, mock_post, notifier):
        """Verify ConnectionError is handled gracefully.

        Mocks requests.post to raise ConnectionError on all attempts.
        Verifies the method returns False without raising, and that
        retries were attempted.
        """
        mock_post.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        result = notifier._post_webhook({"embeds": []})

        assert result is False
        assert mock_post.call_count == notifier._max_retries

    @patch("src.utils.notifier.requests.post")
    def test_timeout_error_handled(self, mock_post, notifier):
        """Verify Timeout is handled gracefully.

        Mocks requests.post to raise Timeout on all attempts. Verifies
        the method returns False without raising.
        """
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        result = notifier._post_webhook({"embeds": []})

        assert result is False
        assert mock_post.call_count == notifier._max_retries


class TestBuildEmbed:
    """Tests for DiscordNotifier._build_embed() output structure."""

    def test_build_embed_structure(self, notifier):
        """Verify _build_embed returns a correctly structured embed dict.

        Checks that all required Discord embed keys are present:
        title, description, color, timestamp, footer, and fields.
        """
        fields = [
            {"name": "Field1", "value": "Value1", "inline": True},
            {"name": "Field2", "value": "Value2", "inline": False},
        ]

        embed = notifier._build_embed(
            title="Test Title",
            description="Test Description",
            color=3447003,
            fields=fields,
        )

        assert embed["title"] == "Test Title"
        assert embed["description"] == "Test Description"
        assert embed["color"] == 3447003
        assert "timestamp" in embed
        assert embed["footer"]["text"] == "A股智能分析系统"
        assert len(embed["fields"]) == 2
        assert embed["fields"][0]["name"] == "Field1"

    def test_build_embed_without_fields(self, notifier):
        """Verify _build_embed works without fields parameter.

        When no fields are provided, the embed should not contain
        a 'fields' key.
        """
        embed = notifier._build_embed(
            title="No Fields",
            description="Description",
            color=5763719,
        )

        assert "fields" not in embed
        assert embed["title"] == "No Fields"
        assert embed["color"] == 5763719


class TestInitialization:
    """Tests for DiscordNotifier.__init__() configuration loading."""

    def test_init_loads_config(self, mock_config, mock_webhook_url):
        """Verify __init__ loads config and sets attributes correctly."""
        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()

        assert notifier.enabled is True
        assert notifier.webhook_url == (
            "https://discord.com/api/webhooks/12345678901234567/ABCDefgh1234567890_abcdefghijklmnop"
        )
        assert notifier._timeout == 10
        assert notifier._max_retries == 3

    def test_init_warns_on_missing_webhook(self, mock_config, monkeypatch):
        """Verify a warning is logged when webhook URL is not set."""
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

        from src.utils.notifier import DiscordNotifier

        with patch("src.utils.notifier.logger") as mock_logger:
            notifier = DiscordNotifier()
            mock_logger.warning.assert_called_once()
            assert "DISCORD_WEBHOOK_URL" in mock_logger.warning.call_args[0][0]

        assert notifier.webhook_url == ""

    @pytest.mark.parametrize(
        "placeholder_url",
        [
            "https://discord.com/api/webhooks/xxxxx/xxxxx",
            "https://discord.com/api/webhooks/12345/xxxxx",
            "not-a-url",
            "https://discord.com/api/webhooks/short/token",
        ],
    )
    def test_init_warns_on_placeholder_webhook(
        self, mock_config, monkeypatch, placeholder_url
    ):
        """Verify placeholder/invalid webhook URLs are detected and disabled."""
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", placeholder_url)

        from src.utils.notifier import DiscordNotifier

        with patch("src.utils.notifier.logger") as mock_logger:
            notifier = DiscordNotifier()
            mock_logger.warning.assert_called_once()
            assert "placeholder" in mock_logger.warning.call_args[0][0].lower()

        assert notifier.webhook_url == ""
        assert notifier._webhook_invalid is True

    @patch("src.utils.notifier.requests.post")
    def test_placeholder_webhook_no_log_spam(self, mock_post, mock_config, monkeypatch):
        """Verify repeated sends with placeholder URL don't spam warning logs."""
        monkeypatch.setenv(
            "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/xxxxx/xxxxx"
        )

        from src.utils.notifier import DiscordNotifier

        notifier = DiscordNotifier()

        with patch("src.utils.notifier.logger") as mock_logger:
            # Multiple sends should NOT produce warning-level logs
            notifier._post_webhook({"embeds": []})
            notifier._post_webhook({"embeds": []})
            notifier._post_webhook({"embeds": []})
            mock_logger.warning.assert_not_called()
            # Should use debug level instead
            assert mock_logger.debug.call_count == 3

        mock_post.assert_not_called()
