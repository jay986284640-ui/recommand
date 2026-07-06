"""Shared pytest fixtures for training-data-synonym."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow synonym-dictionary tests to import synonym_builder
_synonym_dir = Path(__file__).resolve().parent / "synonym-dictionary"
if str(_synonym_dir) not in sys.path:
    sys.path.insert(0, str(_synonym_dir))

from training_data_synonym.common.config import Config
from training_data_synonym.common.llm_client import LLMClient, MockLLMClient
from training_data_synonym.common.logging import configure_logging
from training_data_synonym.hive_reader.mock_reader import MockHiveReader


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent


@pytest.fixture
def configs_dir(repo_root: Path) -> Path:
    return repo_root / "configs"


@pytest.fixture
def fixtures_dir(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures"


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


@pytest.fixture
def cfg(configs_dir: Path) -> Config:
    return Config.load(configs_dir)


@pytest.fixture
def mock_llm() -> LLMClient:
    return MockLLMClient(seed=42)


@pytest.fixture
def mock_hive(fixtures_dir: Path) -> MockHiveReader:
    return MockHiveReader(fixture_dir=fixtures_dir / "hive")


@pytest.fixture(autouse=True)
def _configure_logging() -> None:
    configure_logging(level="WARNING")