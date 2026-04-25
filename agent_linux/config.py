"""Configuration loader for agent-linux."""

import os
import yaml

CONFIG_PATH = "/etc/agent-linux/config.yml"
DEFAULT_CONFIG = {
    "anthropic_api_key": "",
    "monitor": {
        "interval": 60,
        "cpu_threshold": 85,
        "ram_threshold": 90,
        "disk_threshold": 85,
    },
    "thresholds": {
        "docker_restart_alert": 5,
    },
    "allowed_commands": [
        "iptables", "nft", "systemctl", "useradd", "userdel",
        "passwd", "docker", "journalctl", "ss", "ip",
    ],
}


def load_config(path: str = CONFIG_PATH) -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, "r") as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_merge(config, user_cfg)
    return config


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
