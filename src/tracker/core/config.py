"""Loaders for the YAML files in `config/`, validated with pydantic.

Only `sources.yaml` is needed so far. `routes.yaml`, `watched_trips.yaml` and `news_topics.yaml`
get their loaders in the tickets that use them (F1, F6, C2).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    enabled: bool = False
    # Minimum seconds between two requests to the same domain (spec §9 rule 2, "polite").
    min_interval_s: float = Field(default=5.0, ge=0)
    urls: dict[str, str] = Field(default_factory=dict)


class SourcesConfig(BaseModel):
    # dict keeps the YAML order, which is the order the orchestrator runs collectors in.
    sources: dict[str, SourceConfig] = Field(default_factory=dict)


def load_sources(config_dir: Path) -> SourcesConfig:
    raw = yaml.safe_load((config_dir / "sources.yaml").read_text(encoding="utf-8")) or {}
    return SourcesConfig.model_validate(raw)
