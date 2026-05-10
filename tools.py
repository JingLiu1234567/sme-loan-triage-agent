"""
Agent tools for the SME Loan Triage demo.

Three callable tools that the AI agent uses to gather evidence and
record decisions. Each function returns a plain dict so it can be
JSON-serialised back into the LLM tool-use loop.

    1. query_customer_history  - SQL query against bank.db
    2. check_credit_score      - HTTP call to the mock credit bureau
    3. submit_triage_decision  - persist a final decision to the audit log
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx

DB_PATH = Path(__file__).parent / "bank.db"
CREDIT_API_URL = "http://localhost:8000"


def _connect() -> sqlite3.Connection:
    """Open a connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_decisions_table() -> None:
    """Create the audit tables if they do not exist.

    `triage_decisions` logs every agent decision immutably (append-only).
    `reviewer_actions` logs every human reviewer response to those
    decisions, also append-only — accept or override-with-new-decision.
    Together they form the full human-in-the-loop audit trail.
    """
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS triage_decisions (
                decision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL,
                decision       TEXT NOT NULL
                                  CHECK (decision IN ('approve', 'refer', 'decline')),
                reasoning      TEXT NOT NULL,
                key_evidence   TEXT NOT NULL,                       -- JSON list
                risk_flags     TEXT NOT NULL DEFAULT '[]',          -- JSON list
                decided_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decided_by     TEXT NOT NULL DEFAULT 'agent',
                FOREIGN KEY (application_id) REFERENCES loan_applications(application_id)
            );

            CREATE TABLE IF NOT EXISTS reviewer_actions (
                action_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id        INTEGER NOT NULL,
                action             TEXT NOT NULL
                                       CHECK (action IN ('accept', 'override')),
                override_decision  TEXT
                                       CHECK (override_decision IS NULL
                                              OR override_decision IN ('approve', 'refer', 'decline')),
                notes              TEXT,
                reviewed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by        TEXT NOT NULL DEFAULT 'reviewer',
                FOREIGN KEY (decision_id) REFERENCES triage_decisions(decision_id)
            );
        """)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(triage_decisions)")}
        if "risk_flags" not in existing:
            conn.execute(
                "ALTER TABLE triage_decisions "
                "ADD COLUMN risk_flags TEXT NOT NULL DEFAULT '[]'"
            )


_ensure_decisions_table()


# ---------------------------------------------------------------------------
# Tool 1: query_customer_history
# ---------------------------------------------------------------------------
def query_customer_history(customer_id: str) -> dict[str, Any]:
    """Return the customer profile plus aggregated repayment history.

    JOIN-style data assembly happens here so the agent reasons over a
    single dict instead of paging raw rows. Returns an `error` key if
    the customer is unknown.
    """
    with _connect() as conn:
        customer = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()

        if customer is None:
            return {"error": f"customer_id {customer_id} not found"}

        history = conn.execute(
            """
            SELECT record_id, loan_amount_gbp, due_date, paid_date, status
            FROM repayment_history
            WHERE customer_id = ?
            ORDER BY due_date
            """,
            (customer_id,),
        ).fetchall()

        summary = conn.execute(
            """
            SELECT
                COUNT(*)                                              AS total_loans,
                SUM(CASE WHEN status = 'on_time'   THEN 1 ELSE 0 END) AS on_time,
                SUM(CASE WHEN status = 'late'      THEN 1 ELSE 0 END) AS late,
                SUM(CASE WHEN status = 'defaulted' THEN 1 ELSE 0 END) AS defaulted,
                COALESCE(SUM(loan_amount_gbp), 0)                     AS total_borrowed_gbp
            FROM repayment_history
            WHERE customer_id = ?
            """,
            (customer_id,),
        ).fetchone()

    return {
        "customer": dict(customer),
        "summary": dict(summary),
        "history": [dict(r) for r in history],
    }


# ---------------------------------------------------------------------------
# Tool 2: check_credit_score
# ---------------------------------------------------------------------------
def check_credit_score(customer_id: str) -> dict[str, Any]:
    """Call the mock credit-bureau REST API and return the JSON payload.

    Returns an `error` key on network failure or 404. Other HTTP errors
    are raised so we surface them in the agent log rather than silently
    feeding a bad response back to the LLM.
    """
    url = f"{CREDIT_API_URL}/credit-score/{customer_id}"
    try:
        r = httpx.get(url, timeout=5.0)
    except httpx.RequestError as exc:
        return {"error": f"credit bureau unreachable: {exc}"}

    if r.status_code == 404:
        return {"error": f"no credit file for {customer_id}"}
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Tool 3: submit_triage_decision
# ---------------------------------------------------------------------------
def submit_triage_decision(
    application_id: str,
    decision: str,
    reasoning: str,
    key_evidence: list[str],
    risk_flags: list[str],
) -> dict[str, Any]:
    """Persist the agent's final triage decision.

    `decision` must be one of approve / refer / decline. `key_evidence`
    is a list of short evidence strings (e.g. "5 of 5 past loans paid
    on time", "credit score 920 / low band") that justify the choice.
    `risk_flags` is a list of short scannable red-flag tags (e.g.
    "Prior default", "Credit score below 700"). Empty list = no flags.
    """
    if decision not in {"approve", "refer", "decline"}:
        return {"error": f"invalid decision: {decision!r}"}

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO triage_decisions
                (application_id, decision, reasoning, key_evidence, risk_flags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                application_id,
                decision,
                reasoning,
                json.dumps(key_evidence),
                json.dumps(risk_flags),
            ),
        )
        decision_id = cur.lastrowid
        conn.commit()

    return {
        "decision_id": decision_id,
        "application_id": application_id,
        "decision": decision,
        "risk_flag_count": len(risk_flags),
        "status": "recorded",
    }


# ---------------------------------------------------------------------------
# Helper used by the driver code, not exposed as a tool to the agent
# ---------------------------------------------------------------------------
def get_application(application_id: str) -> dict[str, Any] | None:
    """Fetch a pending loan application by id, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM loan_applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Reviewer-side audit functions (human in the loop, not agent tools)
# ---------------------------------------------------------------------------
def record_reviewer_action(
    decision_id: int,
    action: str,
    override_decision: str | None = None,
    notes: str | None = None,
    reviewer: str = "reviewer",
) -> dict[str, Any]:
    """Append a human reviewer's response to an agent triage decision.

    `action` is 'accept' (endorses the agent's recommendation) or
    'override' (replaces it with `override_decision`). Notes are
    required for overrides; the UI enforces that, but we accept any
    string here so the function is reusable.
    """
    if action not in {"accept", "override"}:
        return {"error": f"invalid action: {action!r}"}

    if action == "override":
        if override_decision not in {"approve", "refer", "decline"}:
            return {
                "error": "override requires override_decision in "
                         "{approve, refer, decline}"
            }
    else:
        override_decision = None

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reviewer_actions
                (decision_id, action, override_decision, notes, reviewed_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (decision_id, action, override_decision, notes or None, reviewer),
        )
        action_id = cur.lastrowid
        conn.commit()

    return {
        "action_id": action_id,
        "decision_id": decision_id,
        "action": action,
        "override_decision": override_decision,
        "status": "recorded",
    }


def get_reviewer_action(decision_id: int) -> dict[str, Any] | None:
    """Return the most recent reviewer action for a decision, if any."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM reviewer_actions
            WHERE decision_id = ?
            ORDER BY action_id DESC
            LIMIT 1
            """,
            (decision_id,),
        ).fetchone()
        return dict(row) if row else None
