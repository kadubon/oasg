from __future__ import annotations

from oasg.examples import quickstart_records
from oasg.ledger import seal_records
from oasg.reducers.core import reduce_records


def test_reducer_does_not_repair_protected_debt_without_receipt() -> None:
    first = quickstart_records(improved=False)[0]
    first["event_id"] = "evt_first"
    first["payload"]["protected_debt"]["evidence"] = "critical"
    second = quickstart_records(improved=False)[0]
    second["event_id"] = "evt_second"
    second["payload"]["protected_debt"]["evidence"] = "surplus"
    snapshot = reduce_records(seal_records([first, second]))
    assert snapshot.protected_debt["evidence"] == "critical"


def test_reducer_repairs_protected_debt_with_receipt() -> None:
    first = quickstart_records(improved=False)[0]
    first["event_id"] = "evt_first"
    first["payload"]["protected_debt"]["evidence"] = "critical"
    second = quickstart_records(improved=False)[0]
    second["event_id"] = "evt_second"
    second["payload"]["protected_debt"]["evidence"] = "surplus"
    second["payload"]["repair_receipts"] = [
        {"coordinate": "evidence", "status": "repair_valid"}
    ]
    snapshot = reduce_records(seal_records([first, second]))
    assert snapshot.protected_debt["evidence"] == "surplus"
