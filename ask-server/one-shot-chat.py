#!/usr/bin/env python3
"""One-shot client for SlipStreamAI TCP bridge.

Accepts a compact CLI payload describing the desired server/model/message and
forwards it to the running ask-client bridge. The program prints the response in
`key:value` format so other tools can consume it easily.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, Tuple

import requests
from dotenv import load_dotenv


import locale


load_dotenv()

BRIDGE_HOST = os.getenv("ASK_TCP_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("ASK_TCP_PORT", "8765"))
MODELS_ENDPOINT = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/models"
CHAT_ENDPOINT = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/chat"

STDOUT_ENCODING = sys.stdout.encoding or locale.getpreferredencoding(False) or "utf-8"


def _make_printable(value: str) -> str:
    text = value if isinstance(value, str) else str(value)
    try:
        text.encode(STDOUT_ENCODING)
        return text
    except UnicodeEncodeError:
        return text.encode(STDOUT_ENCODING, errors="replace").decode(
            STDOUT_ENCODING,
            errors="replace",
        )


class InputError(ValueError):
    """Raised when the incoming payload is malformed."""


def read_cli_payload() -> str:
    """Return the raw payload from CLI args or STDIN."""

    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()

    if not sys.stdin.isatty():
        chunk = sys.stdin.read()
        if chunk:
            return chunk.strip()

    raise InputError(
        "No input provided. Supply key/value pairs such as "
        "m:'Hello' s:'Proxy Server' via CLI args or pipe data into stdin."
    )


def parse_payload(raw: str) -> Dict[str, str]:
    """Parse the compact k:'v' payload into a dictionary."""

    pattern = re.compile(
        r"\b(?P<key>s|md|p|c|m)\s*:\s*(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[^\s]+))",
        re.IGNORECASE,
    )

    result: Dict[str, str] = {}
    for match in pattern.finditer(raw):
        key = match.group("key").lower()
        value = match.group("sq") or match.group("dq") or match.group("bare") or ""
        result[key] = value.strip()

    if not result:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip().lower()
            if key in {"s", "md", "p", "c", "m"}:
                result[key] = value.strip()

    if not result:
        result["m"] = raw.strip()

    if "m" not in result or not result["m"]:
        raise InputError("Message field 'm' is required (e.g. m:'Hello world').")

    return result


def fetch_server_defaults() -> Tuple[Dict[str, str], Dict[str, list]]:
    """Fetch defaults and server model lists from the bridge."""

    try:
        response = requests.get(MODELS_ENDPOINT, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to query models endpoint: {exc}") from exc

    payload = response.json()

    defaults = {
        "server": payload.get("default_server", ""),
        "model": payload.get("default_model", ""),
    }

    servers_index: Dict[str, list] = {}
    for entry in payload.get("servers", []):
        name = (entry or {}).get("name")
        if not name:
            continue
        servers_index[name] = list((entry or {}).get("models", []) or [])

    return defaults, servers_index


def resolve_defaults(args: Dict[str, str]) -> Dict[str, str]:
    """Fill in missing fields using bridge defaults and server model list."""

    defaults, servers_index = fetch_server_defaults()

    resolved = dict(args)  # copy

    server_name = resolved.get("s") or defaults.get("server")
    if not server_name:
        server_name = "OpenAI"
    resolved["s"] = server_name 

    model_name = resolved.get("md") or defaults.get("model")
    if not model_name:
        if server_name and server_name in servers_index:
            server_models = servers_index.get(server_name) or []
            if server_models:
                model_name = server_models[0]
        if not model_name:
            model_name = defaults.get("model")
    if not model_name:
        model_name = "gpt-3.5-turbo"
    resolved["md"] = model_name

    return resolved


def build_chat_payload(args: Dict[str, str]) -> Dict[str, Any]:
    """Create the JSON payload for the chat endpoint."""

    payload: Dict[str, Any] = {"message": args["m"], "stream": False}

    if args.get("s"):
        payload["server"] = args["s"]

    if args.get("md"):
        payload["model"] = args["md"]

    if args.get("p"):
        payload["system_prompt"] = args["p"]

    if args.get("c"):
        payload["chat_id"] = args["c"]

    return payload


def send_chat(payload: Dict[str, str]) -> Dict[str, str]:
    """Send the chat request and return the JSON reply."""

    try:
        response = requests.post(
            CHAT_ENDPOINT,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to send chat request: {exc}") from exc

    return response.json()


def main() -> int:
    resolved: Dict[str, str] = {}

    try:
        raw = read_cli_payload()
        parsed = parse_payload(raw)
        resolved = resolve_defaults(parsed)
        chat_payload = build_chat_payload(resolved)
        reply = send_chat(chat_payload)
    except InputError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 3

    chat_id = reply.get("chat_id")
    message = reply.get("message", "")
    model_used = reply.get("model") or reply.get("last_model_used") or resolved.get("md", "")

    if chat_id is None:
        chat_id = resolved.get("c") or ""

    print(f"c:{_make_printable(chat_id)}")
    print(f"m:{_make_printable(message)}")
    print(f"md:{_make_printable(model_used)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
