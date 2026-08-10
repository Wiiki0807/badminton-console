"""One-off cleanup: drop the rows the smoke tests wrote and reset the published state."""
from __future__ import annotations

import json
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root, "api"))

settings_path = os.path.join(root, "api", "local.settings.json")
with open(settings_path, encoding="utf-8") as handle:
    os.environ.update(json.load(handle)["Values"])

from shared import store  # noqa: E402

TEST_NAMES = {"smoke-test", "smoke-admin", "診斷", "球友", "驗證"}

for table_name, name_field in (("comments", "name"), ("wishes", "playerName")):
    removed = 0
    with store._table(table_name) as table:
        for entity in list(table.query_entities(f"PartitionKey eq '{store.PARTITION}'")):
            if entity.get(name_field) in TEST_NAMES:
                table.delete_entity(entity["PartitionKey"], entity["RowKey"])
                removed += 1
    print(f"{table_name}: removed {removed} test row(s)")

store.write_state(dict(store.EMPTY_STATE))
print("state.json: reset to empty")
