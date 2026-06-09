"""Score the RISE oracle's translations the way the paper scores: by EXECUTION.

Self-contained, runs from this directory. For each prompt variant it reads the
translations in outputs/output_{A,B}.jsonl, runs the SOURCE query on PostgreSQL and the
TRANSLATED query on MySQL, and compares the fetched result sets. A translation is correct
iff MySQL executes it without error AND its result set equals PostgreSQL's (plain equality,
order-sensitive -- faithful to the replication package's utils/db.py::verify).

Ground truth is BEHAVIORAL, not a gold string: the "answer" is the rows the source query
returns on PostgreSQL. Both engines must hold the SAME TPC-DS data.

This script does the whole thing itself:
  1. launches PostgreSQL 15 + MySQL 8 as Docker containers (from here, not docker-compose),
  2. generates TPC-DS at a FIXED scale factor with DuckDB and bulk-loads identical data into
     BOTH engines via DuckDB's native postgres/mysql attach extensions (so the data
     generation is folded in here -- no external loader, no CSV round-trip),
  3. scores prompt A into results/results_A.json and prompt B into results/results_B.json,
  4. tears the containers down (set RISE_KEEP_DB=1 to leave them up for debugging).

Caveats (all faithful to the paper's verify, reported as an upper bound):
  - result-set equality is order-sensitive; a query without a total ORDER BY can mis-compare.
  - empty result sets trivially "pass" -> flagged (category empty_pass) for manual review.
  - the paper adds a MANUAL semantic-equivalence check (sec 2.1.3) we do not -> upper bound.
  - MySQL's default collation is case/accent-insensitive; PostgreSQL's is not. That is what
    "running on MySQL" means, so we keep engine defaults.

Reproducibility: hard-aborts unless Docker, the two outputs, and the Python deps are present,
and refuses to overwrite results/results_A.json or results/results_B.json.

    python3 evaluator.py
"""

import os
import sys
import json
import time
import shutil
import subprocess

# ---------------------------------------------------------------- hardcoded config
OUTPUT_A = os.path.join("outputs", "output_A.jsonl")
OUTPUT_B = os.path.join("outputs", "output_B.jsonl")
RESULTS_A = os.path.join("results", "results_A.json")
RESULTS_B = os.path.join("results", "results_B.json")

SCALE_FACTOR = 0.1         # run of record. sf=1 was attempted but is NOT feasible on this
                           # hardware: heavy MySQL queries (e.g. query5) run >1.5h and MySQL's
                           # max_execution_time won't interrupt them. See CHECKLIST.md.
STMT_TIMEOUT_S = 120       # per-query cap (value used for the sf=0.1 run of record). NOTE: PG's
                           # statement_timeout works; MySQL's max_execution_time does NOT reliably
                           # interrupt CTE/INTERSECT queries -- the reason sf=1 is infeasible here.
READY_TIMEOUT_S = 240      # how long to wait for each container to accept connections

PG = {"image": "postgres:15", "name": "rise_eval_pg", "host": "127.0.0.1", "port": 5544,
      "user": "rise", "password": "rise", "db": "tpcds"}
MY = {"image": "mysql:8", "name": "rise_eval_mysql", "host": "127.0.0.1", "port": 3399,
      "user": "rise", "password": "rise", "db": "tpcds"}

# ---------------------------------------------------------------- preconditions (fail fast)
if shutil.which("docker") is None:
    sys.exit("ABORT: docker not found on PATH.")
if not os.path.isfile(OUTPUT_A):
    sys.exit(f"ABORT: missing {OUTPUT_A} (run main.py first)")
if not os.path.isfile(OUTPUT_B):
    sys.exit(f"ABORT: missing {OUTPUT_B} (run main.py first)")
try:
    import duckdb
    import psycopg2
    import mysql.connector
except ModuleNotFoundError as e:
    sys.exit(f"ABORT: missing Python dep ({e.name}); pip install -r requirements.txt")
if os.path.exists(RESULTS_A):
    sys.exit(f"ABORT: output already exists (refusing to overwrite): {RESULTS_A}")
if os.path.exists(RESULTS_B):
    sys.exit(f"ABORT: output already exists (refusing to overwrite): {RESULTS_B}")


# ---------------------------------------------------------------- docker
def docker_rm(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)


def docker_run(args: list) -> None:
    r = subprocess.run(["docker", "run", "-d", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ABORT: docker run failed:\n{r.stderr.strip()}")


def launch_pg() -> None:
    docker_rm(PG["name"])
    docker_run(["--name", PG["name"],
                "-e", f"POSTGRES_USER={PG['user']}",
                "-e", f"POSTGRES_PASSWORD={PG['password']}",
                "-e", f"POSTGRES_DB={PG['db']}",
                "-p", f"{PG['port']}:5432", PG["image"]])


def launch_my() -> None:
    docker_rm(MY["name"])
    docker_run(["--name", MY["name"],
                "-e", f"MYSQL_ROOT_PASSWORD={MY['password']}",
                "-e", f"MYSQL_DATABASE={MY['db']}",
                "-e", f"MYSQL_USER={MY['user']}",
                "-e", f"MYSQL_PASSWORD={MY['password']}",
                "-p", f"{MY['port']}:3306", MY["image"],
                # bulk-insert speed flags (ephemeral DB, durability not needed):
                "--skip-log-bin",
                "--innodb-flush-log-at-trx-commit=0",
                "--innodb-doublewrite=0"])


def pg_connect():
    return psycopg2.connect(host=PG["host"], port=PG["port"], user=PG["user"],
                            password=PG["password"], dbname=PG["db"], connect_timeout=5)


def my_connect():
    return mysql.connector.connect(host=MY["host"], port=MY["port"], user=MY["user"],
                                   password=MY["password"], database=MY["db"],
                                   connection_timeout=5)


def wait_ready(connect_fn, label: str) -> None:
    start = time.time()
    last = None
    while time.time() - start < READY_TIMEOUT_S:
        try:
            connect_fn().close()
            print(f"  {label} ready ({time.time() - start:.0f}s)")
            return
        except Exception as e:  # noqa: BLE001 - any connect error means "not up yet"
            last = e
            time.sleep(2)
    sys.exit(f"ABORT: {label} not ready after {READY_TIMEOUT_S}s: {last}")


# ---------------------------------------------------------------- data: generate + load (folded in)
def build_databases() -> None:
    """Generate TPC-DS sf=SCALE_FACTOR in DuckDB and copy identical data into BOTH engines."""
    con = duckdb.connect()
    print("  loading DuckDB extensions (tpcds, postgres, mysql) ...")
    con.execute("INSTALL tpcds; LOAD tpcds; INSTALL postgres; LOAD postgres; "
                "INSTALL mysql; LOAD mysql;")
    print(f"  generating TPC-DS sf={SCALE_FACTOR} ...")
    con.execute(f"CALL dsdgen(sf={SCALE_FACTOR})")
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name").fetchall()]
    print(f"  {len(tables)} tables generated; attaching engines ...")

    pg_dsn = (f"host={PG['host']} port={PG['port']} user={PG['user']} "
              f"password={PG['password']} dbname={PG['db']}")
    my_dsn = (f"host={MY['host']} port={MY['port']} user={MY['user']} "
              f"password={MY['password']} database={MY['db']}")
    con.execute(f"ATTACH '{pg_dsn}' AS pg (TYPE postgres)")
    con.execute(f"ATTACH '{my_dsn}' AS my (TYPE mysql)")

    for t in tables:
        for alias in ("pg", "my"):
            con.execute(f"DROP TABLE IF EXISTS {alias}.{t}")
            con.execute(f"CREATE TABLE {alias}.{t} AS SELECT * FROM main.{t}")
        print(f"    loaded {t}")
    con.close()
    print("  both engines hold identical data.")


def analyze(pg_conn, my_conn) -> None:
    """Collect table statistics so the planners use hash joins, not nested loops.

    DuckDB's CREATE TABLE AS leaves the engines with NO statistics; without them PostgreSQL
    plans nested-loop joins on the star-schema queries (q4/q11/q74 etc.) and a single query can
    run for minutes. ANALYZE is cheap and turns those into fast hash joins.
    """
    print("  ANALYZE PostgreSQL ...")
    cur = pg_conn.cursor()
    cur.execute("ANALYZE")
    pg_conn.commit()
    cur.close()

    print("  ANALYZE MySQL tables ...")
    cur = my_conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (MY["db"],))
    tables = [r[0] for r in cur.fetchall()]
    cur.close()
    cur = my_conn.cursor(buffered=True)
    for t in tables:
        cur.execute(f"ANALYZE TABLE `{t}`")
        cur.fetchall()
    my_conn.commit()
    cur.close()


def create_indexes(conn, kind: str) -> None:
    """Index every TPC-DS join key (columns ending in _sk) so star-schema joins use seeks,
    not full scans. Derived from the _sk naming convention (covers dimension PKs + fact FKs);
    columns that don't exist are simply not found, so it's robust to schema drift.
    """
    schema = "public" if kind == "pg" else MY["db"]
    cur = conn.cursor()
    cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s", (schema,))
    targets = [(t, c) for (t, c) in cur.fetchall() if c.endswith("_sk")]
    cur.close()
    print(f"  indexing {len(targets)} {kind} join columns ...")
    cur = conn.cursor()
    for t, c in targets:
        name = f"ix_{t}_{c}"[:60]
        try:
            if kind == "pg":
                cur.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{t}" ("{c}")')
            else:
                cur.execute(f"CREATE INDEX `{name}` ON `{t}` (`{c}`)")
            conn.commit()
        except Exception:
            conn.rollback()  # index already exists / unsupported column -> skip
    cur.close()


# ---------------------------------------------------------------- scoring
def setup_session(conn, kind: str) -> None:
    """Set the per-query timeout ONCE per connection (not per query)."""
    cur = conn.cursor()
    if kind == "pg":
        cur.execute(f"SET statement_timeout = {STMT_TIMEOUT_S * 1000}")
    else:
        cur.execute(f"SET SESSION max_execution_time = {STMT_TIMEOUT_S * 1000}")
    conn.commit()
    cur.close()


def statements(sql: str) -> list:
    """Split the oracle's translation into its individual statements, dropping fragments
    that are ONLY comments/whitespace.

    We must run the FULL translation: some TPC-DS queries (14, 23, 24, 39) are genuinely TWO
    statements, so we never truncate the oracle's output. But every query also carries a
    trailing '-- end query' comment after its final ';'; mysql-connector treats that tail as a
    second statement whose empty result is left unread ('Unread result found'), so we drop the
    comment-only fragment. Splitting on ';' is sufficient for TPC-DS (no ';' inside literals).
    """
    out = []
    for chunk in sql.split(";"):
        body = "\n".join(ln for ln in chunk.splitlines() if not ln.strip().startswith("--")).strip()
        if body:
            out.append(chunk)
    return out


def execute_query(conn, sql: str, kind: str):
    """Run ALL of the oracle's statements; return the LAST statement's rows (matching
    psycopg2 / the package's behavior of returning the final result set). Rollback + raise
    on error. MySQL uses a BUFFERED cursor so each result is fully read before the next.
    """
    cur = conn.cursor(buffered=True) if kind == "my" else conn.cursor()
    try:
        rows = None
        for stmt in statements(sql):
            cur.execute(stmt)
            rows = cur.fetchall() if cur.description is not None else rows
        conn.commit()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def verify(pg_conn, source_sql: str, my_conn, target_sql: str):
    """(passed, message, category). Mirrors utils/db.py::verify, but a source that fails on
    PostgreSQL is a FAIL (we can't establish ground truth) rather than a silent pass."""
    try:
        s_result = execute_query(pg_conn, source_sql, "pg")
    except Exception as e:
        return False, f"source failed on PostgreSQL: {e}", "source_error"
    try:
        t_result = execute_query(my_conn, target_sql, "my")
    except Exception as e:
        return False, f"target execution error: {e}", "target_error"
    if s_result != t_result:
        return False, "inequivalent result sets", "mismatch"
    if s_result is not None and len(s_result) == 0:
        return True, "empty-result pass (review)", "empty_pass"
    return True, "pass", "pass"


def score(prompt_label: str, output_path: str, pg_conn, my_conn) -> dict:
    rows = [json.loads(l) for l in open(output_path, encoding="utf-8") if l.strip()]
    print(f"\n=== scoring prompt {prompt_label} ({len(rows)} queries) ===")
    per_query, ok, cats = [], 0, {}
    for r in rows:
        name = r["name"]
        tgt = r.get("translated_query")
        if not isinstance(tgt, str) or not tgt.strip():
            passed, msg, cat = False, "no translation (null/empty)", "no_translation"
        else:
            passed, msg, cat = verify(pg_conn, r["source_query"], my_conn, tgt)
        ok += int(passed)
        cats[cat] = cats.get(cat, 0) + 1
        per_query.append({"query": name, "passed": passed, "category": cat, "message": msg})
        print(f"  {name}: {'PASS' if passed else 'FAIL'} [{cat}]")
    n = len(rows)
    print(f"  -> {ok}/{n} = {round(100 * ok / n, 2) if n else 0}%  {cats}")
    return {
        "prompt": prompt_label,
        "scale_factor": SCALE_FACTOR,
        "statement_timeout_s": STMT_TIMEOUT_S,
        "scoring": ("execution-based result-set equality (order-sensitive); empty results "
                    "flagged; source-fail counted as FAIL; manual semantic check (paper "
                    "sec 2.1.3) NOT applied -> accuracy is an upper bound"),
        "n_queries": n,
        "n_correct": ok,
        "accuracy": round(ok / n, 4) if n else 0.0,
        "categories": cats,
        "per_query": per_query,
    }


def main() -> None:
    try:
        print("Launching containers ...")
        launch_pg()
        launch_my()
        wait_ready(pg_connect, "PostgreSQL")
        wait_ready(my_connect, "MySQL")
        build_databases()

        pg_conn = pg_connect()
        my_conn = my_connect()
        setup_session(pg_conn, "pg")
        setup_session(my_conn, "my")
        create_indexes(pg_conn, "pg")
        create_indexes(my_conn, "my")
        analyze(pg_conn, my_conn)
        report_a = score("A", OUTPUT_A, pg_conn, my_conn)
        report_b = score("B", OUTPUT_B, pg_conn, my_conn)
        pg_conn.close()
        my_conn.close()

        os.makedirs("results", exist_ok=True)
        with open(RESULTS_A, "w", encoding="utf-8") as f:
            json.dump(report_a, f, indent=2)
        with open(RESULTS_B, "w", encoding="utf-8") as f:
            json.dump(report_b, f, indent=2)
        print(f"\nSaved {RESULTS_A} and {RESULTS_B}")
        print(f"  prompt A: {report_a['n_correct']}/{report_a['n_queries']} = "
              f"{report_a['accuracy'] * 100:.2f}%   {report_a['categories']}")
        print(f"  prompt B: {report_b['n_correct']}/{report_b['n_queries']} = "
              f"{report_b['accuracy'] * 100:.2f}%   {report_b['categories']}")
    finally:
        if os.environ.get("RISE_KEEP_DB"):
            print(f"\nRISE_KEEP_DB set -> leaving {PG['name']} / {MY['name']} up "
                  f"(pg:{PG['port']} my:{MY['port']}). Remove with: "
                  f"docker rm -f {PG['name']} {MY['name']}")
        else:
            print("\nTearing down containers ...")
            docker_rm(PG["name"])
            docker_rm(MY["name"])


if __name__ == "__main__":
    main()
