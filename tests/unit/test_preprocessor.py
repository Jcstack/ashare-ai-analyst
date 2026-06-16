"""Unit tests for src/data/preprocessor.py — DataPreprocessor.

Tests for FR-D002 (Data Preprocessing) per PRD Section 4.1:
  - AC-D002-1: Remove suspended trading days (volume=0)
  - AC-D002-2: Forward-fill NaN in price columns
  - AC-D002-3: Align dates across multiple DataFrames (inner join)
  - AC-D002-4: Add derived return columns (daily_return, weekly_return, log_return)
  - AC-D002-5: Input DataFrame immutability
  - Save processed data to parquet in data/processed/

Per PRD Section 6.3 mock strategy:
  - Use tmp_path for file I/O
  - Fixed seed for reproducibility
  - Mock external deps only (not business logic)
"""

import pandas as pd
import numpy as np
from unittest.mock import patch


class TestCleanOHLCV:
    """Tests for DataPreprocessor.clean_ohlcv() or equivalent cleaning method."""

    def test_clean_ohlcv_removes_suspended(self, sample_ohlcv_with_suspension):
        """AC-D002-1: Input with volume=0 row, verify it is removed.

        Suspended trading days are identified by volume == 0.
        After cleaning, no rows with volume == 0 should remain.
        """
        from src.data.preprocessor import DataPreprocessor

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(sample_ohlcv_with_suspension)

        # Original has 10 rows, one with volume=0
        assert len(sample_ohlcv_with_suspension) == 10
        assert (sample_ohlcv_with_suspension["volume"] == 0).sum() == 1

        # After cleaning, no volume=0 rows should exist
        assert (result["volume"] == 0).sum() == 0, (
            "Suspended trading days (volume=0) should be removed"
        )
        assert len(result) == 9, (
            f"Expected 9 rows after removing 1 suspended day, got {len(result)}"
        )

    def test_clean_ohlcv_removes_volume_nan(self, sample_ohlcv_df):
        """AC-D002-1: Rows with volume=NaN should also be removed."""
        from src.data.preprocessor import DataPreprocessor

        df = sample_ohlcv_df.copy()
        df.loc[2, "volume"] = np.nan

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(df)

        assert result["volume"].isna().sum() == 0, (
            "Rows with volume=NaN should be removed"
        )
        assert len(result) == 9

    def test_clean_ohlcv_immutable(self, sample_ohlcv_with_suspension):
        """AC-D002-5: Verify input DataFrame is NOT modified after clean.

        The preprocessing function must return a new DataFrame without
        modifying the original input. This ensures raw data integrity.
        """
        from src.data.preprocessor import DataPreprocessor

        # Take a deep copy of the original for comparison
        original_copy = sample_ohlcv_with_suspension.copy()

        preprocessor = DataPreprocessor()
        _ = preprocessor.clean_ohlcv(sample_ohlcv_with_suspension)

        # Original should be completely unchanged
        pd.testing.assert_frame_equal(
            sample_ohlcv_with_suspension,
            original_copy,
            check_exact=True,
        )

    def test_clean_ohlcv_ffill_missing(self, sample_ohlcv_df):
        """AC-D002-2: Verify NaN in price columns gets forward-filled.

        Price columns (open, high, low, close) with NaN should be
        forward-filled (ffill). After cleaning, no NaN should remain
        in price columns.
        """
        from src.data.preprocessor import DataPreprocessor

        df = sample_ohlcv_df.copy()
        # Introduce NaN in price columns at rows 3 and 5
        df.loc[3, "close"] = np.nan
        df.loc[5, "open"] = np.nan
        df.loc[5, "high"] = np.nan

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(df)

        # After ffill, no NaN should remain in price columns
        price_cols = ["open", "close", "high", "low"]
        for col in price_cols:
            if col in result.columns:
                nan_count = result[col].isna().sum()
                assert nan_count == 0, (
                    f"Column '{col}' should have no NaN after forward-fill, "
                    f"found {nan_count} NaN values"
                )

    def test_clean_ohlcv_ffill_preserves_valid_values(self, sample_ohlcv_df):
        """AC-D002-2: Forward-fill should not overwrite valid values."""
        from src.data.preprocessor import DataPreprocessor

        df = sample_ohlcv_df.copy()
        original_close_0 = df.loc[0, "close"]
        original_close_1 = df.loc[1, "close"]
        df.loc[2, "close"] = np.nan  # Only row 2 is NaN

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(df)

        # Non-NaN values should be preserved
        assert result.iloc[0]["close"] == original_close_0
        assert result.iloc[1]["close"] == original_close_1
        # Row 2 (NaN) should be filled with row 1's value
        assert result.iloc[2]["close"] == original_close_1

    def test_clean_ohlcv_returns_dataframe(self, sample_ohlcv_df):
        """Basic contract: clean_ohlcv should return a DataFrame."""
        from src.data.preprocessor import DataPreprocessor

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(sample_ohlcv_df)

        assert isinstance(result, pd.DataFrame)
        assert not result.empty


class TestAlignDates:
    """Tests for DataPreprocessor.align_dates() — AC-D002-3."""

    def test_align_dates(self):
        """AC-D002-3: Two DFs with different date ranges, output has common dates only.

        When aligning multiple stock DataFrames, the resulting date index
        should be the intersection (inner join) of all input date indices.
        """
        from src.data.preprocessor import DataPreprocessor

        np.random.seed(42)

        # Stock A: Jan 2-11 (10 business days)
        dates_a = pd.date_range("2024-01-02", periods=10, freq="B")
        df_a = pd.DataFrame(
            {
                "date": dates_a,
                "close": np.random.uniform(10, 11, 10),
                "volume": np.random.randint(1000000, 2000000, 10),
            }
        )

        # Stock B: Jan 4-15 (10 business days) — overlaps Jan 4-11 with A
        dates_b = pd.date_range("2024-01-04", periods=10, freq="B")
        df_b = pd.DataFrame(
            {
                "date": dates_b,
                "close": np.random.uniform(20, 22, 10),
                "volume": np.random.randint(500000, 1500000, 10),
            }
        )

        preprocessor = DataPreprocessor()
        result = preprocessor.align_dates({"A": df_a, "B": df_b})

        result_a = result["A"]
        result_b = result["B"]

        # Both results should have the same dates (intersection)
        assert len(result_a) == len(result_b), (
            f"Aligned DataFrames should have same length. "
            f"Got {len(result_a)} and {len(result_b)}"
        )

        # Verify dates are identical
        pd.testing.assert_series_equal(
            result_a["date"].reset_index(drop=True),
            result_b["date"].reset_index(drop=True),
        )

        # The intersection should only include dates present in BOTH
        common_dates = set(dates_a) & set(dates_b)
        result_dates = set(pd.to_datetime(result_a["date"]))
        assert result_dates == common_dates, (
            f"Expected common dates {common_dates}, got {result_dates}"
        )

    def test_align_dates_no_overlap(self):
        """AC-D002-3 edge case: Two DFs with no overlapping dates.

        When there is no date overlap, the aligned DataFrames should
        be empty.
        """
        from src.data.preprocessor import DataPreprocessor

        dates_a = pd.date_range("2024-01-02", periods=5, freq="B")
        df_a = pd.DataFrame(
            {
                "date": dates_a,
                "close": [10.0, 10.1, 10.2, 10.3, 10.4],
                "volume": [1000000] * 5,
            }
        )

        dates_b = pd.date_range("2024-02-01", periods=5, freq="B")
        df_b = pd.DataFrame(
            {
                "date": dates_b,
                "close": [20.0, 20.1, 20.2, 20.3, 20.4],
                "volume": [500000] * 5,
            }
        )

        preprocessor = DataPreprocessor()
        result = preprocessor.align_dates({"A": df_a, "B": df_b})

        assert len(result["A"]) == 0
        assert len(result["B"]) == 0

    def test_align_dates_preserves_columns(self, sample_ohlcv_df):
        """AC-D002-3: Alignment should preserve all original columns."""
        from src.data.preprocessor import DataPreprocessor

        df_a = sample_ohlcv_df.copy()
        # Create df_b with same dates but offset by 2 days
        df_b = sample_ohlcv_df.copy()
        df_b["date"] = pd.date_range("2024-01-04", periods=10, freq="B")

        preprocessor = DataPreprocessor()
        result = preprocessor.align_dates({"A": df_a, "B": df_b})

        # All original columns should be preserved
        assert set(result["A"].columns) == set(df_a.columns)
        assert set(result["B"].columns) == set(df_b.columns)


class TestAddReturns:
    """Tests for DataPreprocessor.add_returns() — AC-D002-4."""

    def test_add_returns(self, sample_ohlcv_df):
        """AC-D002-4: Verify daily_return, log_return columns added.

        The preprocessor should compute and add:
          - daily_return: close.pct_change()
          - log_return: np.log(close / close.shift(1))
        """
        from src.data.preprocessor import DataPreprocessor

        preprocessor = DataPreprocessor()
        result = preprocessor.add_returns(sample_ohlcv_df)

        # Check daily_return column exists
        assert "daily_return" in result.columns, "Column 'daily_return' should be added"

        # Check log_return column exists
        assert "log_return" in result.columns, "Column 'log_return' should be added"

        # Verify daily_return values (close.pct_change())
        expected_daily = sample_ohlcv_df["close"].pct_change()
        pd.testing.assert_series_equal(
            result["daily_return"],
            expected_daily,
            check_names=False,
            atol=1e-10,
        )

        # Verify log_return values (np.log(close / close.shift(1)))
        expected_log = np.log(
            sample_ohlcv_df["close"] / sample_ohlcv_df["close"].shift(1)
        )
        pd.testing.assert_series_equal(
            result["log_return"],
            expected_log,
            check_names=False,
            atol=1e-10,
        )

    def test_add_returns_first_row_nan(self, sample_ohlcv_df):
        """AC-D002-4: First row of return columns should be NaN.

        pct_change() and log return both produce NaN for the first row
        because there is no previous value to compute the change from.
        """
        from src.data.preprocessor import DataPreprocessor

        preprocessor = DataPreprocessor()
        result = preprocessor.add_returns(sample_ohlcv_df)

        assert pd.isna(result["daily_return"].iloc[0]), (
            "First daily_return value should be NaN"
        )
        assert pd.isna(result["log_return"].iloc[0]), (
            "First log_return value should be NaN"
        )

    def test_add_returns_immutable(self, sample_ohlcv_df):
        """AC-D002-5: add_returns should not modify the input DataFrame."""
        from src.data.preprocessor import DataPreprocessor

        original_copy = sample_ohlcv_df.copy()
        original_columns = list(sample_ohlcv_df.columns)

        preprocessor = DataPreprocessor()
        _ = preprocessor.add_returns(sample_ohlcv_df)

        # Original should have the same columns (no new columns added in-place)
        assert list(sample_ohlcv_df.columns) == original_columns, (
            "Input DataFrame should not have new columns added in-place"
        )
        pd.testing.assert_frame_equal(
            sample_ohlcv_df,
            original_copy,
            check_exact=True,
        )

    def test_add_returns_known_values(self):
        """AC-D002-4: Verify return calculations against hand-computed values.

        Known-answer test with simple data for easy manual verification.
        """
        from src.data.preprocessor import DataPreprocessor

        np.random.seed(42)
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-02", periods=5, freq="B"),
                "close": [100.0, 110.0, 105.0, 115.0, 112.0],
                "open": [99.0, 100.0, 110.0, 105.0, 115.0],
                "high": [101.0, 111.0, 111.0, 116.0, 116.0],
                "low": [98.0, 99.0, 104.0, 104.0, 111.0],
                "volume": [1000000] * 5,
            }
        )

        preprocessor = DataPreprocessor()
        result = preprocessor.add_returns(df)

        # Hand-computed daily returns:
        # Row 0: NaN (no previous)
        # Row 1: (110 - 100) / 100 = 0.10
        # Row 2: (105 - 110) / 110 = -0.04545...
        # Row 3: (115 - 105) / 105 = 0.09523...
        # Row 4: (112 - 115) / 115 = -0.02608...
        assert pd.isna(result["daily_return"].iloc[0])
        assert abs(result["daily_return"].iloc[1] - 0.10) < 1e-6
        assert abs(result["daily_return"].iloc[2] - (-5.0 / 110.0)) < 1e-6
        assert abs(result["daily_return"].iloc[3] - (10.0 / 105.0)) < 1e-6
        assert abs(result["daily_return"].iloc[4] - (-3.0 / 115.0)) < 1e-6

        # Hand-computed log returns:
        # Row 1: ln(110/100) = ln(1.1) ~ 0.09531
        # Row 2: ln(105/110) = ln(0.9545) ~ -0.04652
        assert abs(result["log_return"].iloc[1] - np.log(1.1)) < 1e-6
        assert abs(result["log_return"].iloc[2] - np.log(105.0 / 110.0)) < 1e-6


class TestSaveProcessed:
    """Tests for saving processed data to data/processed/."""

    @patch("src.data.preprocessor.get_data_dir")
    def test_save_processed(self, mock_get_data_dir, sample_ohlcv_df, tmp_path):
        """AC-D002-5: Verify saves parquet to data/processed/, file exists."""
        from src.data.preprocessor import DataPreprocessor

        processed_dir = tmp_path / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)
        mock_get_data_dir.return_value = processed_dir

        preprocessor = DataPreprocessor()
        preprocessor.save_processed(
            df=sample_ohlcv_df,
            name="000001",
        )

        # Verify the processed directory exists
        assert processed_dir.exists(), (
            f"Processed directory {processed_dir} should exist"
        )

        # Verify parquet file was written
        parquet_files = list(processed_dir.glob("*.parquet"))
        assert len(parquet_files) >= 1, (
            f"Expected at least one parquet file in {processed_dir}, "
            f"found: {parquet_files}"
        )

        # Verify the saved file can be read back and matches
        saved_df = pd.read_parquet(parquet_files[0])
        assert len(saved_df) == len(sample_ohlcv_df)
        assert set(saved_df.columns) == set(sample_ohlcv_df.columns)

    @patch("src.data.preprocessor.get_data_dir")
    def test_save_processed_does_not_overwrite_raw(
        self, mock_get_data_dir, sample_ohlcv_df, tmp_path
    ):
        """AC-D002-5: Saving processed data does not touch raw directory."""
        from src.data.preprocessor import DataPreprocessor

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        # Place a sentinel file in raw/
        sentinel = raw_dir / "sentinel.txt"
        sentinel.write_text("do not touch")

        processed_dir = tmp_path / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)
        mock_get_data_dir.return_value = processed_dir

        preprocessor = DataPreprocessor()
        preprocessor.save_processed(
            df=sample_ohlcv_df,
            name="000001",
        )

        # Raw directory sentinel should still exist and be unchanged
        assert sentinel.exists()
        assert sentinel.read_text() == "do not touch"

    @patch("src.data.preprocessor.get_data_dir")
    def test_save_processed_creates_directory(
        self, mock_get_data_dir, sample_ohlcv_df, tmp_path
    ):
        """Verify save_processed creates output_dir if it does not exist."""
        from src.data.preprocessor import DataPreprocessor

        output_dir = tmp_path / "processed" / "daily"
        mock_get_data_dir.return_value = output_dir
        assert not output_dir.exists()

        preprocessor = DataPreprocessor()
        preprocessor.save_processed(
            df=sample_ohlcv_df,
            name="600519",
        )

        assert output_dir.exists()
        parquet_files = list(output_dir.glob("*.parquet"))
        assert len(parquet_files) >= 1


class TestEndToEndPreprocessing:
    """Integration-like tests combining multiple preprocessing steps."""

    @patch("src.data.preprocessor.get_data_dir")
    def test_full_preprocessing_pipeline(
        self, mock_get_data_dir, sample_ohlcv_with_suspension, tmp_path
    ):
        """Verify full pipeline: clean -> add_returns -> save.

        This test exercises the full preprocessing flow to ensure the
        steps compose correctly.
        """
        from src.data.preprocessor import DataPreprocessor

        processed_dir = tmp_path / "processed"
        mock_get_data_dir.return_value = processed_dir

        preprocessor = DataPreprocessor()

        # Step 1: Clean (removes suspended day)
        cleaned = preprocessor.clean_ohlcv(sample_ohlcv_with_suspension)
        assert (cleaned["volume"] == 0).sum() == 0
        assert len(cleaned) == 9

        # Step 2: Add returns
        with_returns = preprocessor.add_returns(cleaned)
        assert "daily_return" in with_returns.columns
        assert "log_return" in with_returns.columns

        # Step 3: Save
        preprocessor.save_processed(
            df=with_returns,
            name="000001",
        )
        parquet_files = list(processed_dir.glob("*.parquet"))
        assert len(parquet_files) >= 1

        # Verify saved data is correct
        saved = pd.read_parquet(parquet_files[0])
        assert len(saved) == 9
        assert "daily_return" in saved.columns
        assert "log_return" in saved.columns

    def test_clean_preserves_data_order(self, sample_ohlcv_with_suspension):
        """Verify cleaning preserves chronological order of data."""
        from src.data.preprocessor import DataPreprocessor

        preprocessor = DataPreprocessor()
        result = preprocessor.clean_ohlcv(sample_ohlcv_with_suspension)

        # Dates should remain in ascending order
        if "date" in result.columns:
            dates = pd.to_datetime(result["date"])
            assert dates.is_monotonic_increasing, (
                "Dates should remain in ascending chronological order"
            )
