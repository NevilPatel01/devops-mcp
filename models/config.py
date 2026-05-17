"""Load YAML configuration."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ServiceConfig(BaseModel):
    name: str
    compose_file: str
    sensitive: bool = False
    health_check_url: str | None = None


class ThresholdConfig(BaseModel):
    cpu_percent: float = 80
    memory_percent: float = 85
    disk_percent: float = 90
    container_restart_count: int = 3


class ServerConfig(BaseModel):
    id: str
    label: str
    host: str
    port: int = 22
    user: str = "root"
    ssh_key_path: str = "~/.ssh/id_ed25519"
    services: list[ServiceConfig] = Field(default_factory=list)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)


class ServersFile(BaseModel):
    protected_services: list[str] = Field(default_factory=list)
    servers: list[ServerConfig] = Field(default_factory=list)


class RiskOverride(BaseModel):
    action_type: str
    risk_tier: str


class AutomationConfig(BaseModel):
    poll_interval_seconds: int = 30
    approval_timeout_seconds: int = 60
    auto_execute_risk_tier: str = "low"
    stale_after_hours: int = 24
    correlation_window_minutes: int = 30


class RulesFile(BaseModel):
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    risk_overrides: list[RiskOverride] = Field(default_factory=list)


class AppConfig(BaseModel):
    servers: ServersFile
    rules: RulesFile


def _config_root() -> Path:
    return Path(__file__).resolve().parent.parent / "config"


def load_servers_config(path: Path | None = None) -> ServersFile:
    config_path = path or Path(
        os.getenv("SERVERS_CONFIG_PATH", _config_root() / "servers.yaml")
    )
    if not config_path.exists():
        example = _config_root() / "servers.yaml.example"
        raise FileNotFoundError(
            f"Missing {config_path}. Copy {example} to config/servers.yaml and configure."
        )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return ServersFile.model_validate(data)


def load_rules_config(path: Path | None = None) -> RulesFile:
    config_path = path or Path(os.getenv("RULES_CONFIG_PATH", _config_root() / "rules.yaml"))
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return RulesFile.model_validate(data)


def load_app_config() -> AppConfig:
    return AppConfig(servers=load_servers_config(), rules=load_rules_config())
