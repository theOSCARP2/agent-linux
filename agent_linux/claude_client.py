"""Anthropic Claude integration with tool use for system actions."""

import json
import logging
import os
import socket
import subprocess
from typing import Any

import anthropic

from . import actions as act
from .monitor import get_recent_events

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

# Tool definitions exposed to Claude
TOOLS = [
    {
        "name": "execute_command",
        "description": "Execute an allowed system command on the server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Full shell command to execute"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file on the server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_service_status",
        "description": "Get the systemd status of a service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name (e.g. nginx)"}
            },
            "required": ["service"],
        },
    },
    {
        "name": "get_docker_status",
        "description": "List all Docker containers with their status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_network_rules",
        "description": "Get current firewall rules (nftables or iptables).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_system_metrics",
        "description": "Get real-time CPU, RAM, and disk metrics.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _build_system_prompt() -> str:
    hostname = socket.gethostname()
    interfaces = _get_interfaces()
    docker_services = _detect_docker_services()

    return f"""You are agent-linux, an AI system administrator for the Linux server '{hostname}'.

Server info:
- Hostname: {hostname}
- Network interfaces: {interfaces}
- Docker services detected: {docker_services}

You help the administrator monitor, diagnose, and manage this server.
When you need to execute commands or read files, use the provided tools.
Always explain what you are about to do before invoking a tool.
Be concise, precise, and security-conscious.
Prefer non-destructive operations and warn before making changes."""


def _get_interfaces() -> str:
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        result = []
        for iface, addr_list in addrs.items():
            ips = [a.address for a in addr_list if a.family == 2]  # AF_INET
            if ips:
                result.append(f"{iface}={','.join(ips)}")
        return " ".join(result) or "unknown"
    except Exception:
        return "unknown"


def _detect_docker_services() -> str:
    try:
        import docker as docker_sdk
        client = docker_sdk.from_env()
        names = [c.name for c in client.containers.list()]
        return ", ".join(names) if names else "none"
    except Exception:
        return "unavailable"


class ClaudeClient:
    def __init__(self, config: dict):
        api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._config = config
        self._system_prompt = _build_system_prompt()
        self._conversation: list[dict] = []

    def reset_conversation(self) -> None:
        self._conversation = []

    def chat(self, user_message: str, confirm_callback=None) -> str:
        """Send a user message and return the assistant reply.

        confirm_callback(tool_name, command) -> bool  — called before executing
        any tool that modifies the system. Return False to skip execution.
        """
        recent = get_recent_events(20)
        monitoring_context = (
            f"\n\n[Recent monitoring snapshots (last {len(recent)}):\n"
            + json.dumps(recent, default=str, indent=2)
            + "]"
        ) if recent else ""

        self._conversation.append({"role": "user", "content": user_message})

        messages = self._conversation.copy()
        # Inject monitoring context into the last user message
        if monitoring_context and messages:
            last = messages[-1]
            messages[-1] = {**last, "content": last["content"] + monitoring_context}

        while True:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            # Collect text content for display
            text_parts = [
                b.text for b in response.content if hasattr(b, "text")
            ]
            assistant_text = "\n".join(text_parts)

            if response.stop_reason != "tool_use":
                self._conversation.append(
                    {"role": "assistant", "content": response.content}
                )
                return assistant_text

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = self._dispatch_tool(
                    block.name, block.input, confirm_callback
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    def alert(self, alert_message: str) -> str:
        """Send an autonomous alert from the monitor and return Claude's response."""
        prompt = f"[MONITOR ALERT] {alert_message}\nPlease analyze and recommend action."
        return self.chat(prompt)

    def _dispatch_tool(self, name: str, inputs: dict, confirm_callback) -> dict:
        allowed = self._config.get("allowed_commands", [])

        if name == "execute_command":
            cmd = inputs["command"]
            if confirm_callback and not confirm_callback("execute_command", cmd):
                return {"success": False, "stderr": "User cancelled", "stdout": "", "returncode": -1}
            return act.execute_command(cmd, allowed)

        if name == "read_file":
            return act.read_file(inputs["path"])

        if name == "get_service_status":
            return act.get_service_status(inputs["service"], allowed)

        if name == "get_docker_status":
            return act.get_docker_status(allowed)

        if name == "get_network_rules":
            return act.get_network_rules(allowed)

        if name == "get_system_metrics":
            return act.get_system_metrics()

        return {"success": False, "error": f"Unknown tool: {name}"}
