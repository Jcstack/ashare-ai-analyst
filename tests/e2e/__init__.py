"""End-to-end tests for the A-share analysis platform.

These tests use FastAPI TestClient with dependency_overrides to mock
external boundaries (AKShare, LLM APIs, Redis, yfinance) while running
real service logic end-to-end.
"""
