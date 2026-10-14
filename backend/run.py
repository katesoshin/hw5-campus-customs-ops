"""Command-line runner for the agent team.

    python -m backend.run --ticket 101
    python -m backend.run --agent inventory --task "Is CC-TEE-WHITE S in stock?" --ticket 101
"""

from __future__ import annotations

import argparse
import asyncio
import json

from .agents import run_agent_task, run_ticket
from .models import AGENT_NAMES


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    parser.add_argument("--ticket", type=int, help="ticket id to work")
    parser.add_argument("--agent", choices=AGENT_NAMES, help="run one agent directly instead of Boss")
    parser.add_argument("--task", help="task text for --agent")
    args = parser.parse_args()

    if args.agent:
        if not args.task:
            parser.error("--agent needs --task")
        result = asyncio.run(run_agent_task(args.agent, args.task, ticket_id=args.ticket))
    elif args.ticket is not None:
        result = asyncio.run(run_ticket(args.ticket))
    else:
        parser.error("give --ticket, or --agent with --task")
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
