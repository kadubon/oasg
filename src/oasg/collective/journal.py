"""Bounded local intents and acknowledgments; no cross-store atomicity claim."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from oasg.collective.wire import Contract, Closed, Digest, Name, digest, encoded, loads, sha
from oasg.library import _library_lock


class Entry(Closed):
    previous: Digest
    id: Name
    kind: str
    data: dict[str, Any]
    digest: Digest


def check_ack(data: dict[str, Any]) -> None:
    if (set(data) != {"intent", "original_result", "result_sha256"}
            or not isinstance(data["original_result"], str)
            or sha(data["original_result"].encode()) != data["result_sha256"]):
        raise ValueError("invalid original acknowledgment")


class Journal:
    def __init__(self, root: Path):
        self.path = root / "collective.json"

    def inspect(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"revision": "0" * 64, "entries": [], "unresolved": [], "withdrawn": []}
        raw = loads(self.path.read_bytes())
        if not isinstance(raw, list) or not 1 <= len(raw) <= 128:
            raise ValueError("invalid journal bounds")
        previous = "0" * 64
        identities: set[str] = set()
        unresolved: dict[str, Any] = {}
        withdrawals = []
        for row in raw:
            row = Entry.model_validate(row).model_dump()
            body = {k: row[k] for k in ("previous", "id", "kind", "data")}
            if row["previous"] != previous or digest(body) != row["digest"] or row["id"] in identities:
                raise ValueError("forked or conflicting journal")
            identities.add(row["id"])
            previous = row["digest"]
            if row["kind"] == "intent":
                unresolved[row["id"]] = row
            elif row["kind"] == "ack":
                check_ack(row["data"])
                if row["data"]["intent"] not in unresolved:
                    raise ValueError("acknowledgment without pending intent")
                del unresolved[row["data"]["intent"]]
            elif row["kind"] == "withdraw":
                withdrawals.append(row["data"])
            elif row["kind"] != "register":
                raise ValueError("unknown journal transition")
        if raw[0]["kind"] != "register" or any(r["kind"] == "register" for r in raw[1:]):
            raise ValueError("registration history missing or replaced")
        Contract.model_validate(raw[0]["data"]["contract"])
        return {"revision": previous, "entries": raw, "unresolved": list(unresolved),
                "withdrawn": withdrawals}

    def append(self, kind: str, identity: str, data: dict[str, Any], *, expected: str) -> str:
        # Validate exact bounded JSON before acquiring the lock.
        clean = loads(encoded(data))
        with _library_lock(self.path):
            view = self.inspect()
            for old in view["entries"]:
                if old["id"] == identity:
                    if old["kind"] != kind or old["data"] != clean:
                        raise ValueError("conflicting idempotency key")
                    return old["digest"]
            if view["revision"] != expected:
                raise ValueError("stale journal revision")
            if len(view["entries"]) >= 128:
                raise ValueError("journal full")
            if not view["entries"] and kind != "register":
                raise ValueError("explicit registration required")
            if kind == "register":
                if view["entries"]:
                    raise ValueError("immutable registration")
                Contract.model_validate(clean["contract"])
            elif kind == "ack":
                check_ack(clean)
                if clean.get("intent") not in view["unresolved"]:
                    raise ValueError("not a pending operation")
            elif kind not in {"intent", "withdraw"}:
                raise ValueError("unsupported transition")
            body = {"previous": expected, "id": identity, "kind": kind, "data": clean}
            row = {**body, "digest": digest(body)}
            Entry.model_validate(row)
            raw = encoded([*view["entries"], row])
            loads(raw)
            temporary = self.path.with_suffix(".pending")
            with temporary.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            return row["digest"]

    def require_ready(self, contract: Contract, *, now: int) -> dict[str, Any]:
        view = self.inspect()
        if not view["entries"] or view["entries"][0]["data"]["contract"] != contract.model_dump():
            raise ValueError("unregistered contract")
        if view["unresolved"] or view["withdrawn"]:
            raise ValueError("unresolved operation or scoped withdrawal")
        if not contract.registered_at <= now < contract.expires_at:
            raise ValueError("registration expired")
        return view
