from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fetcher import StockDataFetcher
    from .preprocessor import DataPreprocessor


def __getattr__(name: str):
    if name == "StockDataFetcher":
        from .fetcher import StockDataFetcher

        return StockDataFetcher
    if name == "DataPreprocessor":
        from .preprocessor import DataPreprocessor

        return DataPreprocessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["StockDataFetcher", "DataPreprocessor"]
