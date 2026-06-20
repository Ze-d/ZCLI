from __future__ import annotations

import argparse
from pathlib import Path

from .agent import Agent
from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zcli", description="Persistent personal coding agent")
    parser.add_argument("--workspace", type=Path, help="workspace the agent may access")
    parser.add_argument("--session", default="default", help="session id to open or create")
    parser.add_argument("--new", action="store_true", help="create a fresh named session")
    parser.add_argument("--list-sessions", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.workspace)
    agent = Agent(settings)

    if args.list_sessions:
        for session in agent.sessions.list():
            print(f"{session.id}\t{session.updated_at}\t{len(session.messages)} messages")
        return 0

    session = agent.sessions.create(args.session) if args.new else agent.sessions.load_or_create(args.session)
    print(f"ZCLI 0.1 | workspace: {settings.workspace} | session: {session.id}")
    print("Commands: /exit, /memory, /sessions")
    while True:
        try:
            query = input("zcli >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query in {"/exit", "/quit"}:
            break
        if query == "/memory":
            print(agent.memory.index() or "(no memories)")
            continue
        if query == "/sessions":
            for item in agent.sessions.list():
                print(f"{item.id}\t{item.updated_at}")
            continue
        try:
            agent.run_turn(session, query)
        except Exception as exc:
            print(f"Error: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

