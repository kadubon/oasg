"""Structured opt-in commands; inspection does not initialize any runtime."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from oasg.collective.check import check_projection, check_trial
from oasg.collective.journal import Journal
from oasg.collective.native import support
from oasg.collective.projection import project
from oasg.collective.replay import replay
from oasg.collective.wire import Contract, Source, encoded, loads

app = typer.Typer(help="Opt-in finite collective profile. Read-only checks grant no authority.")


def emit(action: Callable[[], Any]) -> None:
    try:
        result = action()
    except (subprocess.SubprocessError, RuntimeError) as exc:
        sys.stdout.write(
            encoded(
                {
                    "ok": False,
                    "status": "execution_interrupted",
                    "reason": str(exc)[:1000],
                    "next_step": "inspect saved journal; do not repeat an uncertain operation",
                    "execution_authorization": False,
                }
            ).decode()
            + "\n"
        )
        raise typer.Exit(2) from exc
    except (ValueError, KeyError, OSError, ImportError) as exc:
        sys.stdout.write(
            encoded(
                {
                    "ok": False,
                    "status": "rejected",
                    "reason": str(exc)[:1000],
                    "execution_authorization": False,
                }
            ).decode()
            + "\n"
        )
        raise typer.Exit(2) from exc
    sys.stdout.write(encoded(result).decode() + "\n")


@app.command("support")
def support_command() -> None:
    """Read installed versions and declared subset; no imports of companion runtimes."""
    emit(support)


@app.command("inspect")
def inspect_command(path: Annotated[Path, typer.Argument()]) -> None:
    """Read a bounded integration contract without opening or initializing stores."""
    emit(
        lambda: {
            "ok": True,
            "contract": Contract.model_validate(loads(path.read_bytes())).model_dump(),
            "execution_authorization": False,
        }
    )


@app.command("project")
def project_command(contract: Path, source: Path, public_key: str) -> None:
    """Read and project original signed sources; public-key hex is explicit host input."""
    emit(
        lambda: project(
            Contract.model_validate(loads(contract.read_bytes())),
            Source.model_validate(loads(source.read_bytes())),
            bytes.fromhex(public_key),
        )
    )


@app.command("check")
def check_command(contract: Path, report: Path, public_key: str) -> None:
    """Independently reconstruct a projection or paired trial. Never runs a worker."""

    def operation() -> Any:
        c = Contract.model_validate(loads(contract.read_bytes()))
        value = loads(report.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("report must be an object")
        checker = (
            check_trial
            if value.get("schema_id") == "oasg.collective.trial.v1"
            else check_projection
        )
        return checker(c, value, bytes.fromhex(public_key))

    emit(operation)


@app.command("replay")
def replay_command(root: Path) -> None:
    """Read original files and replay receipts; no database, subprocess or network writes."""
    emit(lambda: replay(root))


@app.command("status")
def status_command(root: Path) -> None:
    """Inspect durable intents, acknowledgments and withdrawals without creating files."""
    emit(lambda: Journal(root).inspect())


@app.command("example")
def example_command(
    out: Annotated[Path, typer.Option("--out")],
    execute: Annotated[bool, typer.Option("--execute")] = False,
) -> None:
    """WRITE/EXECUTE: native two-cycle test in an explicit empty disposable directory."""

    def operation() -> Any:
        if not execute:
            return {"status": "execution_opt_in_required", "execution_authorization": False}
        from oasg.collective.runtime import example

        result = example(out)
        return {
            "ok": result["ok"],
            "gate": result["gate"],
            "active": result["active"],
            "work": result["work"],
            "second_cycle_policy": result["second_cycle"]["applied"]["policy"],
            "after_withdrawal_eligible": result["withdrawal"]["memory_eligible"],
            "accounting": result["accounting"]["status"],
            "report": str(out / "report.json"),
            "evidence_class": result["evidence_class"],
            "operationally_observed": False,
        }

    emit(operation)


@app.command("reconcile")
def reconcile_command(root: Path, apply: Annotated[bool, typer.Option("--apply")] = False) -> None:
    """WRITE: independently check accounting and ask CCR to reconcile; never retries uncertain work."""

    def operation() -> Any:
        if not apply:
            return {"status": "write_opt_in_required", "execution_authorization": False}
        from oasg.collective.feedback import reconcile

        return reconcile(root)

    emit(operation)
