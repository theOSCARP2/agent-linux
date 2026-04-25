# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-04-25

### Added
- Initial release
- AI-powered Linux server administration via Claude Sonnet (`claude-sonnet-4-6`)
- systemd daemon with Unix socket IPC
- 60-second monitoring loop: CPU, RAM, disk, Docker, network, auth log, firewall hash, failed services
- Configurable alert thresholds with automatic Claude notification
- Secure command execution with allowlist (`actions.py`)
- 6 Claude tools: `execute_command`, `read_file`, `get_service_status`, `get_docker_status`, `get_network_rules`, `get_system_metrics`
- Interactive chat CLI with Rich formatting and readline history
- `agent-linux install` one-command setup (deps, system user, sudoers, service, API key)
- `agent-linux remove` clean uninstall
- `get.sh` bootstrap script
- Sliding context: last 20 monitoring snapshots injected into every Claude request
- Hardened systemd service (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`)
- Restricted sudoers: only `iptables`, `nft`, `systemctl`, `useradd`, `userdel`, `passwd`

[Unreleased]: https://github.com/theOSCARP2/agent-linux/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/theOSCARP2/agent-linux/releases/tag/v1.0.0
