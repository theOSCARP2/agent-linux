# agent-linux

AI-powered Linux server administration agent using Claude (Anthropic).

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/theOSCARP2/agent-linux/master/get.sh | sudo bash
sudo agent-linux install
```

Then open the interactive chat:

```bash
agent-linux
```

## Commands

| Command | Description |
|---|---|
| `agent-linux install` | Full installation (deps, user, service, API key) |
| `agent-linux remove` | Clean uninstall |
| `agent-linux start` | Start the daemon |
| `agent-linux stop` | Stop the daemon |
| `agent-linux restart` | Restart the daemon |
| `agent-linux status` | Show systemd service status |
| `agent-linux` | Open interactive chat |

## Architecture

```
agent-linux/
├── get.sh                  # One-line bootstrap
├── agent_linux/
│   ├── daemon.py           # systemd service
│   ├── monitor.py          # 60s monitoring loop
│   ├── actions.py          # Allowlisted command execution
│   ├── claude_client.py    # Anthropic API + tool use
│   ├── socket_server.py    # Unix socket IPC
│   └── config.py           # Config loader
├── cli/
│   └── agent_linux_cli.py  # CLI entry point
├── systemd/
│   └── agent-linux.service
└── sudoers.d/
    └── agent-linux
```

## What it monitors (every 60 seconds)

- CPU, RAM, disk usage with configurable alert thresholds
- Docker containers (status, restart count, resource usage)
- Active network connections and open ports
- SSH authentication attempts (`/var/log/auth.log`)
- Firewall rule changes (hash-based detection)
- Failed systemd services

## Security

- Dedicated `agent-linux` system user (no login shell)
- Unix socket with `660` permissions, `agent-linux` group
- Commands executed only through `actions.py` allowlist
- Sudo restricted to: `iptables`, `nft`, `systemctl`, `useradd`, `userdel`, `passwd`
- API key stored in `/etc/agent-linux/config.yml` with `600` permissions

## Configuration

See [`config.yml.example`](config.yml.example). After install, edit `/etc/agent-linux/config.yml`.

## Requirements

- Ubuntu 22.04 / 24.04 or Debian 12
- Python 3.10+
- systemd
