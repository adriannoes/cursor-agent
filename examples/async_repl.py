#!/usr/bin/env python3
"""Async REPL spike example (PRD-000 T2).

Executable integration demo: AsyncClient.launch_bridge, Composer 2.5, multi-turn
context, and cold-start measurement. Not importable production API.
"""

# Cold start measured: ~4.33s on 2026-06-15 (host=adrianno, model=composer-2.5).
# Re-measure: `uv run python examples/async_repl.py` with CURSOR_API_KEY set.

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time

from cursor_sdk import AsyncClient, LocalAgentOptions

COMPOSER_MODEL = "composer-2.5"
MEMORABLE_TOKEN = "PLUMBA-7742"
CURSOR_DASHBOARD_URL = "https://cursor.com/dashboard/integrations"


def validate_cursor_api_key() -> bool:
    """Return True when CURSOR_API_KEY is set; otherwise print guidance and return False.

    Example:
        >>> os.environ["CURSOR_API_KEY"] = "test-key"
        >>> validate_cursor_api_key()
        True
    """
    if os.environ.get("CURSOR_API_KEY"):
        return True

    print(
        "CURSOR_API_KEY is not set.\n"
        "Export CURSOR_API_KEY in your shell; see .env.example and "
        f"{CURSOR_DASHBOARD_URL}",
        file=sys.stderr,
    )
    return False


def response_recalls_token(response_text: str, token: str) -> bool:
    """Return True when *response_text* references *token* (case-insensitive).

    Example:
        >>> response_recalls_token("The codeword was PLUMBA-7742.", "PLUMBA-7742")
        True
    """
    normalized_response = response_text.casefold()
    normalized_token = token.casefold()
    return normalized_token in normalized_response


async def run_two_turn_demo(workspace: str) -> float:
    """Run bridge + agent with two turns; return cold-start seconds for turn one.

    Turn one establishes a memorable token; turn two must recall it.

    Args:
        workspace: Local workspace path passed to launch_bridge and LocalAgentOptions.

    Returns:
        Cold-start latency in seconds (first send through first response text).

    Raises:
        SystemExit: When the second turn does not reference the first-turn token.
    """
    # Local-first for CLI/gateway (launch_bridge + local cwd); cloud reserved for
    # batch jobs — aligned with FR-7 and STRATEGY.md section 7.
    async with await AsyncClient.launch_bridge(workspace=workspace) as client:
        async with await client.agents.create(
            model=COMPOSER_MODEL,
            local=LocalAgentOptions(cwd=workspace),
        ) as agent:
            first_prompt = (
                f"Remember this secret codeword exactly: {MEMORABLE_TOKEN}. "
                "Reply with only ACK."
            )
            cold_start_started = time.perf_counter()
            first_run = await agent.send(first_prompt)
            first_response = await first_run.text()
            cold_start_seconds = time.perf_counter() - cold_start_started

            print("--- Turn 1 ---")
            print(first_response)
            print()

            second_prompt = (
                "What was the secret codeword I gave you in our first message? "
                "Reply with only that codeword."
            )
            second_run = await agent.send(second_prompt)
            second_response = await second_run.text()

            print("--- Turn 2 ---")
            print(second_response)
            print()

            if not response_recalls_token(second_response, MEMORABLE_TOKEN):
                print(
                    "Second turn did not reference the first-turn token "
                    f"{MEMORABLE_TOKEN!r}.",
                    file=sys.stderr,
                )
                raise SystemExit(3)

            return cold_start_seconds


async def main() -> None:
    """Entry point: validate API key, run demo, report cold start."""
    if not validate_cursor_api_key():
        raise SystemExit(1)

    workspace = os.getcwd()
    cold_start_seconds = await run_two_turn_demo(workspace)

    host = socket.gethostname()
    print(
        f"Cold start (turn 1): {cold_start_seconds:.2f}s "
        f"(host={host}, model={COMPOSER_MODEL})"
    )


if __name__ == "__main__":
    asyncio.run(main())
