"""Qlib quantitative prediction adapter — optional actuary engine.

Thin wrapper around Microsoft Qlib for alpha factor extraction and
stock scoring. Supports three modes (tried in order):

1. **Remote**: When the Qlib microservice is running (``qlib-service``
   container or ``QLIB_SERVICE_URL`` env var).
2. **In-process**: When Qlib is installed in the current Python (rare).
3. **Subprocess bridge**: When Qlib lives in a separate ``.venv-qlib``
   (Python 3.11), delegates to ``scripts/qlib_worker.py`` via subprocess.

Gracefully degrades when no mode is available (Docker/CI).
Follows the same try-import guard pattern as ``src/data/qmt_adapter.py``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from src.utils.config import get_project_root, load_config
from src.utils.logger import get_logger

# --- In-process Qlib (if available in current venv) ---
try:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D as QlibData
    from qlib.workflow import R as QlibRecorder

    _HAS_QLIB = True
except ImportError:
    qlib = None  # type: ignore[assignment]
    QlibData = None  # type: ignore[assignment]
    QlibRecorder = None  # type: ignore[assignment]
    _HAS_QLIB = False

# --- Subprocess bridge (if .venv-qlib exists) ---
_QLIB_VENV_PYTHON = get_project_root() / ".venv-qlib" / "bin" / "python"
_QLIB_WORKER = get_project_root() / "scripts" / "qlib_worker.py"
_HAS_QLIB_VENV = _QLIB_VENV_PYTHON.exists() and _QLIB_WORKER.exists()

logger = get_logger("prediction.qlib_adapter")


class QlibAdapter:
    """Adapter for Qlib quantitative prediction engine.

    Automatically selects the best available mode:
    1. In-process Qlib (if installed in current Python)
    2. Subprocess bridge via ``.venv-qlib/bin/python scripts/qlib_worker.py``
    3. Graceful degradation (all methods return None/empty)

    Config is loaded from ``config/research.yaml`` → ``actuary`` section.
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._config: dict[str, Any] = {}
        self._mode: str = "none"  # "remote" | "inprocess" | "subprocess" | "none"
        self._remote: Any = None  # QlibRemoteAdapter instance (lazy)
        self._load_config()

    def _load_config(self) -> None:
        """Load actuary config from research.yaml."""
        try:
            research_cfg = load_config("research")
            self._config = research_cfg.get("actuary", {})
        except FileNotFoundError:
            logger.warning("config/research.yaml not found, using defaults")
            self._config = {}

    def initialize(self) -> bool:
        """Initialize the Qlib engine (remote, in-process, or subprocess).

        Returns:
            True if Qlib is available in any mode.
        """
        # Try remote service first
        try:
            from src.prediction.qlib_remote import QlibRemoteAdapter

            remote = QlibRemoteAdapter()
            if remote.is_available():
                self._remote = remote
                self._initialized = True
                self._mode = "remote"
                logger.info("Qlib available via remote service")
                return True
        except Exception as exc:
            logger.debug("Qlib remote service not available: %s", exc)

        # Try in-process
        if _HAS_QLIB:
            try:
                provider_uri = self._config.get(
                    "qlib_provider_uri", "~/.qlib/qlib_data/cn_data"
                )
                qlib.init(provider_uri=provider_uri, region=REG_CN)
                self._initialized = True
                self._mode = "inprocess"
                logger.info("Qlib initialized (in-process), provider=%s", provider_uri)
                return True
            except Exception as exc:
                logger.warning("Qlib in-process init failed: %s", exc)

        # Try subprocess bridge
        if _HAS_QLIB_VENV:
            try:
                result = self._call_worker(["health"])
                if result and result.get("installed"):
                    self._initialized = True
                    self._mode = "subprocess"
                    logger.info(
                        "Qlib available via subprocess bridge (v%s)",
                        result.get("version", "?"),
                    )
                    return True
            except Exception as exc:
                logger.warning("Qlib subprocess bridge failed: %s", exc)

        logger.info("Qlib not available — actuary engine disabled")
        self._mode = "none"
        return False

    def is_available(self) -> bool:
        """Check if Qlib actuary engine is usable.

        Returns:
            True if Qlib is available (in-process or subprocess).
        """
        if self._initialized:
            return True
        return self.initialize()

    def predict(
        self,
        symbols: list[str],
        horizon: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run Qlib prediction for the given symbols.

        Args:
            symbols: List of 6-digit stock codes (e.g. ["600519", "000001"]).
            horizon: Prediction horizon in trading days. Defaults to config value.

        Returns:
            Dict mapping symbol to prediction result:
            ``{symbol: {"score": float, "ic": float, "features": list}}``.
            Returns empty dict if Qlib is unavailable.
        """
        if not self.is_available():
            return {}

        horizon = horizon or self._config.get("default_horizon", 5)

        if self._mode == "remote":
            return self._remote.predict(symbols, horizon)
        if self._mode == "subprocess":
            return self._predict_subprocess(symbols, horizon)
        return self._predict_inprocess(symbols, horizon)

    def get_ic_value(self, symbol: str) -> float | None:
        """Get the Information Coefficient for a symbol's prediction.

        Args:
            symbol: 6-digit stock code.

        Returns:
            IC value as float, or None if unavailable.
        """
        if not self.is_available():
            return None

        if self._mode == "remote":
            return self._remote.get_ic_value(symbol)
        if self._mode == "subprocess":
            result = self._call_worker(["ic", "--symbol", symbol])
            if result:
                return result.get("ic")
            return None
        return self._ic_inprocess(symbol)

    def get_alpha_factors(self, symbol: str) -> dict[str, float] | None:
        """Get alpha factor values for a symbol.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Dict of factor name to value, or None if unavailable.
        """
        if not self.is_available():
            return None

        if self._mode == "remote":
            return self._remote.get_alpha_factors(symbol)
        if self._mode == "subprocess":
            result = self._call_worker(["alpha", "--symbol", symbol])
            if result:
                return result.get("alpha_factors")
            return None
        return self._alpha_inprocess(symbol)

    def get_health_info(self) -> dict[str, Any]:
        """Return health/status information for the Qlib adapter.

        Returns:
            Dict with installed, initialized, mode, config details.
        """
        info = {
            "installed": _HAS_QLIB,
            "venv_available": _HAS_QLIB_VENV,
            "initialized": self._initialized,
            "mode": self._mode,
            "enabled": self._config.get("enabled", True),
            "model": self._config.get("default_model", "LGBModel"),
            "horizon": self._config.get("default_horizon", 5),
        }
        if self._mode == "remote":
            try:
                info.update(self._remote.get_health_info())
            except Exception:
                pass
        elif self._mode == "subprocess":
            try:
                health = self._call_worker(["health"])
                if health:
                    info["qlib_version"] = health.get("version")
            except Exception:
                pass
        return info

    # ------------------------------------------------------------------
    # Subprocess bridge
    # ------------------------------------------------------------------

    def _call_worker(
        self, args: list[str], timeout: float = 30.0
    ) -> dict[str, Any] | None:
        """Call qlib_worker.py via subprocess and parse JSON output."""
        cmd = [str(_QLIB_VENV_PYTHON), str(_QLIB_WORKER)] + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(get_project_root()),
            )
            if proc.returncode != 0:
                logger.warning("Qlib worker failed: %s", proc.stderr.strip())
                return None
            # Parse last line of stdout as JSON (worker may log to stderr)
            stdout = proc.stdout.strip()
            if not stdout:
                return None
            # Take the last line (JSON output)
            last_line = stdout.split("\n")[-1]
            return json.loads(last_line)
        except subprocess.TimeoutExpired:
            logger.warning("Qlib worker timed out after %.0fs", timeout)
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Qlib worker communication error: %s", exc)
            return None

    def _predict_subprocess(
        self, symbols: list[str], horizon: int
    ) -> dict[str, dict[str, Any]]:
        """Run prediction via subprocess bridge."""
        result = self._call_worker(
            ["predict", "--symbols", ",".join(symbols), "--horizon", str(horizon)],
            timeout=60.0,
        )
        if result and isinstance(result, dict):
            return result
        return {}

    # ------------------------------------------------------------------
    # In-process methods (used when Qlib is in current venv)
    # ------------------------------------------------------------------

    def _predict_inprocess(
        self, symbols: list[str], horizon: int
    ) -> dict[str, dict[str, Any]]:
        """Run prediction using in-process Qlib."""
        results: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            try:
                qlib_code = self._to_qlib_code(symbol)
                features = self._get_features(qlib_code)
                score = self._compute_score(qlib_code, horizon)
                ic = self._ic_inprocess(symbol)

                results[symbol] = {
                    "score": score,
                    "ic": ic,
                    "features": features,
                    "horizon": horizon,
                    "model": self._config.get("default_model", "LGBModel"),
                }
            except Exception as exc:
                logger.warning("Qlib predict failed for %s: %s", symbol, exc)
                results[symbol] = {
                    "score": None,
                    "ic": None,
                    "features": [],
                    "horizon": horizon,
                    "error": str(exc),
                }
        return results

    def _ic_inprocess(self, symbol: str) -> float | None:
        """Compute IC value using in-process Qlib."""
        try:
            qlib_code = self._to_qlib_code(symbol)
            lookback = self._config.get("ic_lookback_days", 60)
            pred_data = QlibData.features(
                [qlib_code],
                fields=["Ref($close, -1)/$close - 1"],
                start_time=f"-{lookback}d",
            )
            if pred_data is None or pred_data.empty or len(pred_data) < 10:
                return None
            return float(pred_data.iloc[:, 0].autocorr())
        except Exception as exc:
            logger.warning("Qlib IC failed for %s: %s", symbol, exc)
            return None

    def _alpha_inprocess(self, symbol: str) -> dict[str, float] | None:
        """Compute alpha factors using in-process Qlib."""
        try:
            qlib_code = self._to_qlib_code(symbol)
            factor_exprs = [
                ("momentum_5d", "Ref($close, -5)/$close - 1"),
                ("momentum_20d", "Ref($close, -20)/$close - 1"),
                ("volatility_20d", "Std($close, 20)/Mean($close, 20)"),
                ("turnover_ratio", "$volume/Ref($volume, 5)"),
                ("price_to_ma20", "$close/Mean($close, 20) - 1"),
            ]
            factors: dict[str, float] = {}
            for name, expr in factor_exprs:
                data = QlibData.features([qlib_code], fields=[expr], start_time="-1d")
                if data is not None and not data.empty:
                    factors[name] = float(data.iloc[-1, 0])
            return factors if factors else None
        except Exception as exc:
            logger.warning("Qlib alpha failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_qlib_code(symbol: str) -> str:
        """Convert 6-digit stock code to Qlib format."""
        if symbol.startswith("6") or symbol.startswith("9"):
            return f"SH{symbol}"
        return f"SZ{symbol}"

    def _get_features(self, qlib_code: str) -> list[str]:
        """Get feature names used for prediction."""
        return self._config.get("features", ["Alpha158"])

    def _compute_score(self, qlib_code: str, horizon: int) -> float | None:
        """Compute prediction score using Qlib recorder."""
        try:
            records = QlibRecorder.list_recorders(experiment_name="stock_pred")
            if not records:
                return None
            latest = list(records.values())[-1]
            pred = latest.load_object("pred.pkl")
            if pred is None:
                return None
            if qlib_code in pred.index.get_level_values(0):
                import math

                score = float(pred.loc[qlib_code].iloc[-1])
                return 1.0 / (1.0 + math.exp(-score))
            return None
        except Exception as exc:
            logger.debug("Qlib score computation: %s", exc)
            return None
