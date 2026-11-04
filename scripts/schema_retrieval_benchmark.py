"""Would retrieving schema help? Measures table recall and prompt size with no model.

A table is "needed" if SQLite's authorizer reports the reference query reading it.
Recall below 100% means the model would be asked to write a query without seeing a table.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_agent.config import ROOT, Settings
from portfolio_agent.db import LOAD_ORDER, connect_readonly, ensure_database
from portfolio_agent.evaluation import load_extended, load_ground_truth
from portfolio_agent.metadata import SchemaCatalog
from portfolio_agent.prompts import build_system_prompt


def tables_read(db: Path, sql: str) -> set[str]:
    conn = connect_readonly(db)
    found: set[str] = set()

    def spy(action, arg1, *_):
        if action == sqlite3.SQLITE_READ and arg1 in LOAD_ORDER:
            found.add(arg1)
        return sqlite3.SQLITE_OK

    conn.set_authorizer(spy)
    conn.execute(sql).fetchall()
    conn.close()
    return found


def main() -> None:
    settings = Settings.from_env()
    ensure_database(settings)
    catalog = SchemaCatalog(settings.db_path)
    cases = load_ground_truth(ROOT / "ground_truth_dataset.json") + load_extended(ROOT / "eval" / "extended_dataset.json")
    cases = [c for c in cases if c.sql]
    full_prompt = len(build_system_prompt(catalog.render()))

    complete = 0
    retrieved_chars = 0
    started = time.perf_counter()
    misses = []
    for case in cases:
        chosen = set(catalog.retrieve_tables(case.question))
        retrieved_chars += len(build_system_prompt(catalog.render(list(chosen))))
        missing = tables_read(settings.db_path, case.sql) - chosen
        complete += not missing
        if missing:
            misses.append(f"  {case.id}: missing {sorted(missing)} for: {case.question}")
    elapsed = (time.perf_counter() - started) * 1000 / len(cases)

    print(f"Questions with a reference query : {len(cases)}")
    print(f"Questions with every table found : {complete}/{len(cases)} ({complete / len(cases):.0%})")
    print(f"System prompt, full schema       : ~{full_prompt // 4} tokens ({full_prompt} chars)")
    print(f"System prompt, retrieved (mean)  : ~{retrieved_chars // len(cases) // 4} tokens")
    print(f"Retrieval plus measuring, per question: {elapsed:.2f} ms")
    if misses:
        print("Misses:")
        print("\n".join(misses))


if __name__ == "__main__":
    main()
