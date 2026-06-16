"""Repair a corrupt agent.db by copying all recoverable data to a fresh DB."""

import os
import sqlite3
import sys


def repair(src: str) -> None:
    bak = src + ".bak"
    tmp = src + ".tmp"

    # Open corrupt DB with bytes factory to avoid UTF-8 decode errors
    old = sqlite3.connect(src)
    old.text_factory = lambda b: b.decode("utf-8", errors="replace")

    # Get table schemas
    schema_rows = old.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
    ).fetchall()

    new = sqlite3.connect(tmp)
    new.execute("PRAGMA journal_mode=WAL")

    for (sql,) in schema_rows:
        tbl_name = sql.split("(")[0].split()[-1].strip('"')
        print(f"Creating table: {tbl_name}")
        new.execute(sql)

    # Copy indexes
    idx_rows = old.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall()
    for (sql,) in idx_rows:
        try:
            new.execute(sql)
        except Exception:
            pass

    # Copy data table by table
    tbl_names = old.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()

    for (tbl,) in tbl_names:
        try:
            rows = old.execute(f'SELECT * FROM "{tbl}"').fetchall()  # noqa: S608
            if not rows:
                print(f"  {tbl}: 0 rows")
                continue
            ncols = len(rows[0])
            placeholders = ",".join(["?"] * ncols)
            copied = 0
            for row in rows:
                try:
                    new.execute(
                        f'INSERT OR IGNORE INTO "{tbl}" VALUES ({placeholders})',  # noqa: S608
                        row,
                    )
                    copied += 1
                except Exception:
                    pass  # skip unrecoverable rows
            print(f"  {tbl}: {copied}/{len(rows)} rows")
        except Exception as e:
            print(f"  {tbl}: FAILED - {e}")

    new.commit()
    result = new.execute("PRAGMA integrity_check").fetchone()
    print(f"New DB integrity: {result[0]}")
    old.close()
    new.close()

    # Swap
    if os.path.exists(bak):
        os.remove(bak)
    os.rename(src, bak)
    os.rename(tmp, src)
    print(f"Done — repaired DB at {src}, backup at {bak}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/agent.db"
    repair(path)
