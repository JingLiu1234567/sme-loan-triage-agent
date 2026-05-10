"""
Streamlit UI for the SME Loan Triage Agent.

Run:
    streamlit run app.py

The app calls into agent.triage_stream() and renders each event live
(application details, tool calls, tool results, final decision) plus a
running audit log of all decisions.
"""

import json
import sqlite3
from pathlib import Path

import streamlit as st

from agent import triage_stream
from tools import get_application, get_reviewer_action, record_reviewer_action

DB_PATH = Path(__file__).parent / "bank.db"

st.set_page_config(
    page_title="SME Loan Triage Agent",
    layout="wide",
)

st.title("SME Loan Triage Agent")
st.caption(
    "Demo · An AI agent reviews a UK SME loan application using an internal "
    "SQL database, an external credit-bureau REST API, and an LLM with "
    "tool use. Final decisions are written to an immutable audit log."
)

# ---------------------------------------------------------------------------
# Sidebar — application picker
# ---------------------------------------------------------------------------
APP_OPTIONS = {
    "APP001 — ABC Bakery (strong borrower)":        "APP001",
    "APP002 — Pixel Print Studio (medium)":         "APP002",
    "APP003 — Sunrise Cafe (weak, prior default)":  "APP003",
}

st.sidebar.header("Pick an application")
choice = st.sidebar.selectbox("Application", list(APP_OPTIONS.keys()))
selected_id = APP_OPTIONS[choice]

run_button = st.sidebar.button(
    "Run triage",
    type="primary",
    use_container_width=True,
)

st.sidebar.divider()
st.sidebar.markdown(
    "**Architecture**\n\n"
    "1. SQL → `bank.db` for repayment history\n"
    "2. REST → mock credit-bureau on `:8000`\n"
    "3. LLM → DeepSeek (OpenAI-compatible)\n"
    "4. Audit → `triage_decisions` (agent) +\n"
    "    `reviewer_actions` (human accept/override)"
)

# ---------------------------------------------------------------------------
# Application details panel
# ---------------------------------------------------------------------------
app = get_application(selected_id)
st.subheader("Application details")
if app:
    c1, c2, c3 = st.columns(3)
    c1.metric("Application", app["application_id"])
    c2.metric("Customer", app["customer_id"])
    c3.metric("Requested", f"GBP {app['requested_amount_gbp']:,}")
    st.caption(f"Purpose · {app['purpose']}")
    st.caption(f"Submitted · {app['submitted_at']}")

# ---------------------------------------------------------------------------
# Run the agent and render events live
# ---------------------------------------------------------------------------
DECISION_RENDERERS = {
    "approve": st.success,
    "refer":   st.warning,
    "decline": st.error,
}

if run_button:
    st.subheader("Agent reasoning")
    final = None
    with st.spinner("Agent is thinking…"):
        for event in triage_stream(selected_id):
            t = event["type"]
            if t == "turn_start":
                st.markdown(f"**Turn {event['turn']}**")
            elif t == "tool_call":
                with st.expander(
                    f"TOOL CALL · {event['name']}({json.dumps(event['args'])})",
                    expanded=False,
                ):
                    st.json(event["args"])
            elif t == "tool_result":
                with st.expander(
                    f"  └─ result · {event['name']}",
                    expanded=False,
                ):
                    st.json(event["result"])
            elif t == "agent_text":
                st.info(event["text"])
            elif t == "error":
                st.error(event["message"])
            elif t == "final":
                final = event

    if final and final.get("decision"):
        st.session_state["pending_review"] = {
            "selected_id": selected_id,
            "decision_record": final["decision"],
            "tool_call_log": final["tool_call_log"],
        }
    elif final is not None:
        st.error("Agent finished without producing a decision.")

# ---------------------------------------------------------------------------
# Agent recommendation + reviewer (Sarah) panel
# Persists across reruns via session_state so that clicking
# Accept / Override does not wipe the displayed decision.
# ---------------------------------------------------------------------------
pending = st.session_state.get("pending_review")
if pending and pending["selected_id"] == selected_id:
    d = pending["decision_record"]
    decision_id = d["_persisted"]["decision_id"]
    agent_decision = d["decision"]
    verdict = agent_decision.upper()
    renderer = DECISION_RENDERERS.get(agent_decision, st.info)

    st.subheader("Agent recommendation")
    renderer(f"**{verdict}**")

    flags = d.get("risk_flags", []) or []
    st.markdown(f"**Risk flags** ({len(flags)})")
    if flags:
        st.markdown(" ".join(f":red-background[{f}]" for f in flags))
    else:
        st.markdown(":green-background[No risk flags]")

    st.markdown("**Reasoning**")
    st.write(d["reasoning"])
    st.markdown("**Key evidence**")
    for ev in d.get("key_evidence", []):
        st.markdown(f"- {ev}")

    with st.expander("Raw event log (all tool calls + results)"):
        st.json(pending["tool_call_log"])

    # ---- Reviewer panel ---------------------------------------------------
    st.divider()
    st.subheader("Reviewer decision")
    existing_review = get_reviewer_action(decision_id)
    if existing_review:
        when = existing_review["reviewed_at"]
        who = existing_review["reviewed_by"]
        if existing_review["action"] == "accept":
            st.success(
                f"Accepted agent's recommendation ({verdict}) — {who} at {when}"
            )
        else:
            override = (existing_review.get("override_decision") or "").upper()
            st.warning(
                f"Overridden to **{override}** (agent had recommended "
                f"{verdict}) — {who} at {when}"
            )
        if existing_review.get("notes"):
            st.markdown(f"**Reviewer notes:** {existing_review['notes']}")
    else:
        st.caption(
            "Sarah's call: accept the agent's recommendation, or override it "
            "with a different decision and notes for the audit trail."
        )
        accept_clicked = st.button(
            f"Accept agent recommendation ({verdict})",
            type="primary",
            use_container_width=True,
            key=f"accept_{decision_id}",
        )
        if accept_clicked:
            record_reviewer_action(decision_id, "accept")
            st.rerun()

        with st.form(f"override_form_{decision_id}"):
            st.markdown("**Or override:**")
            options = ["approve", "refer", "decline"]
            default_idx = (
                options.index(agent_decision) if agent_decision in options else 0
            )
            new_decision = st.selectbox("New decision", options, index=default_idx)
            notes = st.text_area(
                "Reason for override (required)",
                placeholder=(
                    "e.g. Spoke with the customer; new contract mitigates the "
                    "credit-score concern."
                ),
            )
            override_clicked = st.form_submit_button(
                "Submit override",
                use_container_width=True,
            )
            if override_clicked:
                if not notes.strip():
                    st.error("Override requires reviewer notes.")
                elif new_decision == agent_decision:
                    st.error(
                        f"New decision matches agent's ({agent_decision}). "
                        "Use Accept instead."
                    )
                else:
                    record_reviewer_action(
                        decision_id,
                        "override",
                        override_decision=new_decision,
                        notes=notes.strip(),
                    )
                    st.rerun()

# ---------------------------------------------------------------------------
# Audit log — read fresh from DB each render
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Audit log")
st.caption(
    "Every decision is appended here immutably for governance. The "
    "audit table is independent of the LLM session."
)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT
        d.decision_id,
        d.application_id,
        d.decision        AS agent_decision,
        d.risk_flags,
        d.decided_at,
        r.action          AS reviewer_action,
        r.override_decision,
        r.notes           AS reviewer_notes,
        r.reviewed_at
    FROM triage_decisions d
    LEFT JOIN reviewer_actions r
      ON r.action_id = (
          SELECT MAX(action_id)
          FROM reviewer_actions
          WHERE decision_id = d.decision_id
      )
    ORDER BY d.decision_id DESC
    """
).fetchall()
conn.close()

if rows:
    audit_rows = []
    for r in rows:
        row = dict(r)
        try:
            flags = json.loads(row.get("risk_flags") or "[]")
        except json.JSONDecodeError:
            flags = []
        row["risk_flag_count"] = len(flags)
        row["risk_flags"] = ", ".join(flags) if flags else ""

        action = row.get("reviewer_action")
        if action == "accept":
            row["final_outcome"] = (row["agent_decision"] or "").upper()
        elif action == "override":
            row["final_outcome"] = (
                (row.get("override_decision") or "").upper() + " (overridden)"
            )
        else:
            row["final_outcome"] = "Pending review"
        audit_rows.append(row)

    st.dataframe(
        audit_rows,
        use_container_width=True,
        hide_index=True,
        column_order=[
            "decision_id",
            "application_id",
            "agent_decision",
            "reviewer_action",
            "final_outcome",
            "risk_flag_count",
            "risk_flags",
            "reviewer_notes",
            "decided_at",
            "reviewed_at",
        ],
    )
else:
    st.info("No decisions logged yet. Click 'Run triage' on the left to add one.")
