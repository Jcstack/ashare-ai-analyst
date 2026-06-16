"""Interactive chart visualisation for A-share stock analysis.

Uses *plotly* to produce interactive HTML charts that can be saved to
the ``reports/`` directory for review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_DIR = _PROJECT_ROOT / "reports"


class ChartVisualizer:
    """Create interactive plotly charts for price and indicator data.

    Parameters
    ----------
    reports_dir : Path | str | None
        Directory where HTML charts are saved.  Defaults to
        ``<project_root>/reports/``.
    """

    def __init__(self, reports_dir: Path | str | None = None) -> None:
        self.reports_dir = Path(reports_dir) if reports_dir else _REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Candlestick (K-line) chart
    # ------------------------------------------------------------------

    def plot_candlestick(
        self,
        df: pd.DataFrame,
        title: str = "K-Line Chart",
        indicators: Sequence[str] | None = None,
    ) -> go.Figure:
        """Plot a candlestick chart with optional indicator overlays.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with ``open``, ``high``, ``low``, ``close``
            columns and a DatetimeIndex (or a ``date`` column).
        title : str
            Chart title.
        indicators : Sequence[str] | None
            Column names to overlay on the price chart (e.g.
            ``["MA_5", "MA_20", "BB_upper", "BB_lower"]``).

        Returns
        -------
        go.Figure
            The plotly Figure object.
        """
        date_col = self._resolve_date_axis(df)

        fig = go.Figure()

        fig.add_trace(
            go.Candlestick(
                x=date_col,
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="K-Line",
                increasing_line_color="#EF5350",  # red up (A-share convention)
                decreasing_line_color="#26A69A",  # green down
            )
        )

        if indicators:
            for col in indicators:
                if col in df.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=date_col,
                            y=df[col],
                            mode="lines",
                            name=col,
                            line=dict(width=1),
                        )
                    )

        fig.update_layout(
            title=title,
            xaxis_title="Date",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            template="plotly_white",
        )
        return fig

    # ------------------------------------------------------------------
    # Technical indicator subplots
    # ------------------------------------------------------------------

    def plot_indicators(
        self,
        df: pd.DataFrame,
        indicators: Sequence[str] | None = None,
    ) -> go.Figure:
        """Plot technical indicators in stacked subplots.

        By default the method looks for MACD, RSI, KDJ, and Volume
        columns.  You can override this by passing a list of indicator
        group names.

        Supported groups: ``"macd"``, ``"rsi"``, ``"kdj"``, ``"volume"``.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with indicator columns already computed.
        indicators : Sequence[str] | None
            Indicator groups to plot.  Defaults to all available.

        Returns
        -------
        go.Figure
            The plotly Figure object.
        """
        available_groups = self._detect_indicator_groups(df)
        groups = (
            [g for g in indicators if g in available_groups]
            if indicators
            else available_groups
        )

        if not groups:
            raise ValueError("No plottable indicator groups found in the DataFrame.")

        date_col = self._resolve_date_axis(df)
        n_rows = len(groups)

        subplot_titles = [g.upper() for g in groups]
        fig = make_subplots(
            rows=n_rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            subplot_titles=subplot_titles,
        )

        for idx, group in enumerate(groups, start=1):
            if group == "macd":
                self._add_macd_subplot(fig, df, date_col, row=idx)
            elif group == "rsi":
                self._add_rsi_subplot(fig, df, date_col, row=idx)
            elif group == "kdj":
                self._add_kdj_subplot(fig, df, date_col, row=idx)
            elif group == "volume":
                self._add_volume_subplot(fig, df, date_col, row=idx)

        fig.update_layout(
            height=300 * n_rows,
            template="plotly_white",
            showlegend=True,
            xaxis_rangeslider_visible=False,
        )
        return fig

    # ------------------------------------------------------------------
    # Support / Resistance overlay
    # ------------------------------------------------------------------

    def plot_support_resistance(
        self,
        df: pd.DataFrame,
        levels: list[dict],
    ) -> go.Figure:
        """Overlay horizontal support/resistance lines on a price chart.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with OHLCV columns.
        levels : list[dict]
            Each dict must contain ``"level"`` (float) and ``"type"``
            (``"support"`` or ``"resistance"``).  Typically produced by
            :meth:`PatternRecognizer.find_support_resistance`.

        Returns
        -------
        go.Figure
            A candlestick figure with S/R lines drawn.
        """
        fig = self.plot_candlestick(df, title="Support / Resistance Levels")
        self._resolve_date_axis(df)

        for entry in levels:
            price = entry["level"]
            sr_type = entry.get("type", "support")
            colour = "#26A69A" if sr_type == "support" else "#EF5350"
            label = f"{sr_type.capitalize()} {price:.2f}"
            touches = entry.get("touches", "")
            if touches:
                label += f" ({touches}x)"

            fig.add_hline(
                y=price,
                line_dash="dash",
                line_color=colour,
                line_width=1,
                annotation_text=label,
                annotation_position="top left",
            )

        return fig

    # ------------------------------------------------------------------
    # Save helper
    # ------------------------------------------------------------------

    def save_chart(self, fig: go.Figure, filename: str) -> Path:
        """Save a plotly figure as an interactive HTML file.

        Parameters
        ----------
        fig : go.Figure
            The figure to save.
        filename : str
            File name (with or without ``.html`` extension).

        Returns
        -------
        Path
            Absolute path of the saved file.
        """
        if not filename.endswith(".html"):
            filename += ".html"
        filepath = self.reports_dir / filename
        fig.write_html(str(filepath))
        return filepath

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_date_axis(df: pd.DataFrame) -> pd.Series | pd.Index:
        """Return the date axis: use the index if it is datetime, else a
        ``date`` column, else fall back to the integer index."""
        if isinstance(df.index, pd.DatetimeIndex):
            return df.index
        if "date" in df.columns:
            return df["date"]
        return df.index

    @staticmethod
    def _detect_indicator_groups(df: pd.DataFrame) -> list[str]:
        """Return a list of indicator group names present in *df*."""
        groups: list[str] = []
        if "MACD" in df.columns:
            groups.append("macd")
        if "RSI" in df.columns:
            groups.append("rsi")
        if "KDJ_K" in df.columns:
            groups.append("kdj")
        if "volume" in df.columns:
            groups.append("volume")
        return groups

    # -- subplot painters ----------------------------------------------

    @staticmethod
    def _add_macd_subplot(
        fig: go.Figure,
        df: pd.DataFrame,
        date_col: pd.Series | pd.Index,
        row: int,
    ) -> None:
        colours = [
            "#EF5350" if v >= 0 else "#26A69A" for v in df["MACD_hist"].fillna(0)
        ]
        fig.add_trace(
            go.Bar(
                x=date_col,
                y=df["MACD_hist"],
                marker_color=colours,
                name="MACD Hist",
                showlegend=True,
            ),
            row=row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=date_col,
                y=df["MACD"],
                mode="lines",
                name="MACD",
                line=dict(color="blue", width=1),
            ),
            row=row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=date_col,
                y=df["MACD_signal"],
                mode="lines",
                name="Signal",
                line=dict(color="orange", width=1),
            ),
            row=row,
            col=1,
        )

    @staticmethod
    def _add_rsi_subplot(
        fig: go.Figure,
        df: pd.DataFrame,
        date_col: pd.Series | pd.Index,
        row: int,
    ) -> None:
        fig.add_trace(
            go.Scatter(
                x=date_col,
                y=df["RSI"],
                mode="lines",
                name="RSI",
                line=dict(color="purple", width=1),
            ),
            row=row,
            col=1,
        )
        # Overbought / oversold reference lines
        fig.add_hline(
            y=70, line_dash="dash", line_color="red", line_width=0.5, row=row, col=1
        )
        fig.add_hline(
            y=30, line_dash="dash", line_color="green", line_width=0.5, row=row, col=1
        )

    @staticmethod
    def _add_kdj_subplot(
        fig: go.Figure,
        df: pd.DataFrame,
        date_col: pd.Series | pd.Index,
        row: int,
    ) -> None:
        for col, colour in [
            ("KDJ_K", "blue"),
            ("KDJ_D", "orange"),
            ("KDJ_J", "purple"),
        ]:
            if col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=date_col,
                        y=df[col],
                        mode="lines",
                        name=col,
                        line=dict(color=colour, width=1),
                    ),
                    row=row,
                    col=1,
                )

    @staticmethod
    def _add_volume_subplot(
        fig: go.Figure,
        df: pd.DataFrame,
        date_col: pd.Series | pd.Index,
        row: int,
    ) -> None:
        colours = [
            "#EF5350" if c >= o else "#26A69A" for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(
            go.Bar(
                x=date_col,
                y=df["volume"],
                marker_color=colours,
                name="Volume",
                showlegend=True,
            ),
            row=row,
            col=1,
        )
