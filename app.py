"""
Streamlit UI for the SME Loan Triage Agent.

Run:
    streamlit run app.py

The app calls into agent.triage_stream() and renders each event live
(application details, tool calls, tool results, final decision) plus a
running audit log of all decisions.
"""

import html as html_lib
import json
import sqlite3
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from agent import triage_stream
from report import render_report
from tools import (
    get_application,
    get_prior_reviews,
    get_reviewer_action,
    record_reviewer_action,
)

DB_PATH = Path(__file__).parent / "bank.db"

st.set_page_config(
    page_title="SME Loan Triage Agent",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Theme — mirrors the Blue Professional audit report so the dashboard and
# the generated report share one visual identity. Streamlit's native
# widgets still show through (selectbox, dataframe, etc.); the goal is
# brand consistency, not pixel-for-pixel parity with the report.
# ---------------------------------------------------------------------------
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap');

:root {
  --bg: #FDFAE7;
  --primary: #1E2BFA;
  --text: #111111;
  --text-muted: #6B6B6B;
  --text-light: #9A9A9A;
  --accent-light: rgba(30, 43, 250, 0.08);
  --border: rgba(30, 43, 250, 0.2);
  --card-bg: rgba(30, 43, 250, 0.04);
  --ok: #059669;
  --warn: #1E2BFA;
  --bad: #dc2626;
}

/* Apply Inter only to text containers, NOT to arbitrary spans/divs.
   Streamlit ships Material Symbols icons as <span> elements whose
   text content is a ligature (e.g. "arrow_right"); forcing Inter on
   them breaks the ligature and leaks the raw icon name into the UI. */
.stApp,
.stApp p,
.stApp li,
.stApp label,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMarkdownContainer"] * {
  font-family: 'Inter', sans-serif;
}

/* Restore icon fonts — Streamlit uses Material Symbols Rounded /
   Outlined for expanders, help tooltips, selectbox chevrons, etc. */
.stApp [class*="material-symbols"],
.stApp [class*="material-icons"],
.stApp [class*="MaterialIcon"],
.stApp .material-symbols-rounded,
.stApp .material-symbols-outlined,
.stApp i[class*="icon"] {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
}

.stApp { background: var(--bg); }

/* Typography */
h1, h2, h3, h4, h5, h6,
[data-testid="stHeading"] h1,
[data-testid="stHeading"] h2,
[data-testid="stHeading"] h3 {
  font-family: 'Space Grotesk', sans-serif !important;
  letter-spacing: -0.02em !important;
  color: var(--text) !important;
}
h1 { font-weight: 700 !important; }
h2, h3 { font-weight: 600 !important; }

/* Accent line above every subheader (h3) — section rhythm */
[data-testid="stHeading"] h3::before,
.stMarkdown h3::before {
  content: '';
  display: block;
  width: 48px;
  height: 3px;
  background: var(--primary);
  border-radius: 2px;
  margin-bottom: 0.7rem;
}

/* Buttons — pill shape, brand color */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 100px !important;
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 500 !important;
  letter-spacing: 0.01em !important;
  border: 1.5px solid var(--border) !important;
  transition: all .2s ease !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {
  background: var(--primary) !important;
  border-color: var(--primary) !important;
  color: #fff !important;
}
.stButton > button[kind="primary"]:hover { filter: brightness(0.92); }

/* Toggle */
.stToggle label { font-family: 'Space Grotesk', sans-serif !important; }

/* Sidebar */
[data-testid="stSidebar"] {
  background: var(--bg) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] hr { border-color: var(--border) !important; }

/* Metric cards (used in Application details) */
[data-testid="stMetric"] {
  background: var(--card-bg);
  border: 1.5px solid var(--border);
  border-radius: 14px;
  padding: 1rem 1.2rem;
}
[data-testid="stMetricValue"] {
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 700 !important;
  color: var(--primary) !important;
}
[data-testid="stMetricLabel"] {
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.75rem !important;
  color: var(--text-muted) !important;
}

/* Outer (Streamlit) expanders — used now as collapsible section
   wrappers (Prior history, Agent reasoning, Raw event log). Styled
   as clean header strips, NOT cards, so any cards inside don't
   collide with an outer card background. */
[data-testid="stExpander"] {
  border: none !important;
  background: transparent !important;
  border-radius: 0 !important;
  margin: 0.4rem 0 1rem !important;
}
[data-testid="stExpander"] summary {
  cursor: pointer;
  padding: 0.6rem 0 !important;
  border-bottom: 1px solid var(--border) !important;
}
[data-testid="stExpander"] summary p {
  font-family: 'Space Grotesk', sans-serif !important;
  font-size: 1.05rem !important;
  font-weight: 600 !important;
  color: var(--text) !important;
  letter-spacing: -0.01em !important;
}

/* Inner native <details> for tool-call / tool-result blocks inside
   the Agent-reasoning trace. Streamlit forbids nested st.expander,
   so we render these as plain HTML and style them card-like + small. */
details.trace-details {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.45rem 0.85rem;
  margin: 0.3rem 0;
}
details.trace-details summary {
  cursor: pointer;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.82rem;
  color: var(--text-muted);
  font-weight: 500;
  padding: 0.15rem 0;
}
details.trace-details summary::marker { color: var(--primary); }
details.trace-details > pre {
  background: rgba(0,0,0,0.04);
  padding: 0.7rem 0.9rem;
  border-radius: 6px;
  font-family: ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace;
  font-size: 0.75rem;
  color: var(--text);
  overflow-x: auto;
  margin: 0.5rem 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 380px;
  overflow-y: auto;
}

/* Captions */
[data-testid="stCaptionContainer"] { color: var(--text-muted) !important; }

/* DataFrame */
[data-testid="stDataFrame"] {
  border-radius: 12px !important;
  border: 1px solid var(--border) !important;
  overflow: hidden;
}

/* Custom: tag pills */
.tag-pill {
  display: inline-block;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.78rem;
  font-weight: 500;
  padding: 0.35rem 0.9rem;
  border-radius: 100px;
  margin: 0.2rem 0.3rem 0.2rem 0;
  color: var(--bad);
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.15);
}
.tag-pill.clean {
  color: var(--ok);
  background: rgba(5, 150, 105, 0.08);
  border-color: rgba(5, 150, 105, 0.2);
}

/* Custom: decision card (replaces st.success/warning/error banner) */
.decision-card {
  display: flex; flex-direction: column; gap: 0.4rem;
  padding: 1.4rem 1.6rem;
  border-radius: 14px;
  border: 1.5px solid var(--border);
  background: var(--card-bg);
  margin: 0.4rem 0 1.2rem;
}
.decision-card .eyebrow {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  font-weight: 600;
}
.decision-card .verdict {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 2.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1;
}
.decision-card.approve .verdict { color: var(--ok); }
.decision-card.refer .verdict    { color: var(--primary); }
.decision-card.decline .verdict  { color: var(--bad); }
.decision-card .meta {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-top: 0.3rem;
}

/* Custom: reviewer status card */
.review-card {
  display: flex; gap: 0.9rem; align-items: flex-start;
  padding: 1rem 1.2rem;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--card-bg);
  margin: 0.4rem 0 0.8rem;
}
.review-card.accepted   { border-color: rgba(5,150,105,0.4); background: rgba(5,150,105,0.05); }
.review-card.overridden { border-color: rgba(220,38,38,0.35); background: rgba(220,38,38,0.04); }
.review-card .badge {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 0.25rem 0.7rem;
  border-radius: 100px;
  flex-shrink: 0;
}
.review-card.accepted   .badge { color: var(--ok);  background: rgba(5,150,105,0.12); }
.review-card.overridden .badge { color: var(--bad); background: rgba(220,38,38,0.12); }
.review-card .body { font-size: 0.95rem; color: var(--text); line-height: 1.45; }
.review-card .body strong { font-family: 'Space Grotesk', sans-serif; }
.review-card .when { font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem; }

/* Two-column section headers — Agent vs Reviewer.
   Cobalt accent for the AI side; warm amber for the human side. Same
   structural pattern (stripe + eyebrow + title), different colour to
   signal "machine pre-screen" vs "human sign-off" at a glance. */
.section-header {
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.6rem;
}
.section-header .accent-stripe {
  width: 48px;
  height: 3px;
  border-radius: 2px;
  margin-bottom: 0.7rem;
}
.section-header.agent    .accent-stripe { background: var(--primary); }
.section-header.reviewer .accent-stripe { background: #B45309; }
.section-header .eyebrow {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.section-header.agent    .eyebrow { color: var(--primary); }
.section-header.reviewer .eyebrow { color: #B45309; }
.section-header .title {
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 600;
  font-size: 1.3rem;
  color: var(--text);
  letter-spacing: -0.02em;
}

/* Live agent-reasoning trace — small grey "thinking" style so the
   verdict card below is the real focal point. Targets the elements
   inside the "Agent reasoning" section (turn markers, agent_text,
   nested tool-call expanders). */
.thinking-turn {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-light);
  margin: 0.8rem 0 0.3rem;
}
.thinking-text {
  color: var(--text-muted);
  font-size: 0.85rem;
  line-height: 1.6;
  padding-left: 0.9rem;
  border-left: 2px solid var(--border);
  margin: 0.3rem 0 0.5rem;
}

/* Prior triage history — dedicated panel above Run triage so the human
   sees the customer's track record at this bank before reading the
   agent's recommendation. Each record is a card; overridden records
   are emphasised because they indicate the bank's actual risk appetite. */
.prior-summary {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 0.6rem;
}
.prior-summary .pill {
  display: inline-block;
  padding: 0.2rem 0.7rem;
  border-radius: 100px;
  background: var(--accent-light);
  color: var(--primary);
  font-weight: 600;
  margin-right: 0.4rem;
}
.prior-summary .pill.warn {
  color: var(--bad);
  background: rgba(220, 38, 38, 0.08);
}

.prior-record {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 1rem 1.2rem;
  border-radius: 12px;
  background: var(--card-bg);
  border: 1px solid var(--border);
  margin-bottom: 0.6rem;
}
.prior-record.overridden { border-color: rgba(220,38,38,0.35); }
.prior-record.accepted   { border-color: rgba(5,150,105,0.3); }
.prior-record .row1 {
  display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 0.78rem;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}
.prior-record .row1 .app-id { color: var(--text); font-weight: 600; }
.prior-record .row1 .sep { opacity: 0.5; }
.prior-record .outcome {
  font-size: 0.95rem;
  color: var(--text);
  line-height: 1.4;
}
.prior-record .outcome .agent {
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 600;
}
.prior-record .outcome .arrow {
  color: var(--text-light);
  margin: 0 0.4rem;
  font-family: 'Space Grotesk', sans-serif;
}
.prior-record .outcome .final {
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
}
.prior-record.overridden .outcome .final { color: var(--bad); }
.prior-record.accepted   .outcome .final { color: var(--ok); }
.prior-record .notes {
  font-size: 0.85rem;
  color: var(--text-muted);
  font-style: italic;
  line-height: 1.5;
  padding-top: 0.3rem;
  border-top: 1px dashed var(--border);
}

.no-prior {
  padding: 0.9rem 1.2rem;
  border-radius: 12px;
  background: var(--card-bg);
  border: 1px dashed var(--border);
  color: var(--text-muted);
  font-size: 0.9rem;
}

/* Tighten Streamlit chrome */
#MainMenu, footer { visibility: hidden; }
</style>
"""
st.markdown(_THEME_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Small HTML renderers — used for elements where Streamlit's default
# look (st.success / :red-background[] / etc.) doesn't match the
# report's visual register.
# ---------------------------------------------------------------------------
_DECISION_LABEL = {"approve": "APPROVE", "refer": "REFER", "decline": "DECLINE"}


def decision_card_html(decision: str) -> str:
    """Big verdict card that replaces st.success/warning/error."""
    key = decision if decision in _DECISION_LABEL else "refer"
    blurb = {
        "approve": "Low-risk profile. Green-light for the relationship manager.",
        "refer":   "Mixed evidence. Escalate to a senior human reviewer.",
        "decline": "Clear risk signals. Recommend rejection.",
    }[key]
    return (
        f'<div class="decision-card {key}">'
        f'<div class="eyebrow">Agent verdict</div>'
        f'<div class="verdict">{_DECISION_LABEL[key]}</div>'
        f'<div class="meta">{blurb}</div>'
        f'</div>'
    )


def flag_pills_html(flags: list[str]) -> str:
    """Rounded pill tags for risk flags."""
    if not flags:
        return '<span class="tag-pill clean">No risk flags</span>'
    return "".join(f'<span class="tag-pill">{f}</span>' for f in flags)


def render_tool_event(name: str, kind: str, payload) -> str:
    """Render one tool_call or tool_result as an HTML <details> block.

    Used both for live-streaming events during a run and for the static
    replay from session_state once the run has completed (so the trace
    doesn't vanish the moment the user accepts/overrides).
    """
    if kind == "call":
        title = f"TOOL CALL · {name}({json.dumps(payload)})"
    else:
        title = f"└─ result · {name}"
    body = json.dumps(payload, indent=2, default=str)
    return (
        f'<details class="trace-details">'
        f'<summary>{html_lib.escape(title)}</summary>'
        f'<pre>{html_lib.escape(body)}</pre></details>'
    )


def prior_history_html(prior: dict) -> str:
    """Render the prior-triage panel for this customer.

    Shows up before the agent runs so the human reviewer can see the
    customer's track record at a glance. If the agent has never seen this
    customer, show a small "new customer" hint instead.
    """
    history = prior.get("history") or []
    if not history:
        return (
            '<div class="no-prior">'
            'No prior triage on record for this customer. The agent will '
            'evaluate this application on its own merits.'
            '</div>'
        )

    override_count = prior.get("override_count", 0)
    prior_count = prior.get("prior_count", len(history))
    pill_class = "pill warn" if override_count else "pill"
    summary = (
        f'<div class="prior-summary">'
        f'<span class="{pill_class}">{prior_count} prior</span>'
        f'<span class="{pill_class}">{override_count} overridden</span>'
        f'When this customer last applied, here is what happened.'
        f'</div>'
    )

    cards = []
    for rec in history[:5]:
        action = rec.get("reviewer_action")
        agent = (rec.get("agent_decision") or "").upper()
        decided_at = (rec.get("decided_at") or "").split(".")[0]
        app_id = rec.get("application_id") or ""
        decision_id = rec.get("decision_id") or ""

        if action == "override":
            cls = "overridden"
            final = (rec.get("override_decision") or "").upper()
            outcome = (
                f'<span class="agent">Agent: {agent}</span>'
                f'<span class="arrow">→</span>'
                f'<span>Reviewer overrode to </span>'
                f'<span class="final">{final}</span>'
            )
        elif action == "accept":
            cls = "accepted"
            outcome = (
                f'<span class="agent">Agent: {agent}</span>'
                f'<span class="arrow">·</span>'
                f'<span>Reviewer accepted </span>'
                f'<span class="final">{agent}</span>'
            )
        else:
            cls = ""
            outcome = (
                f'<span class="agent">Agent: {agent}</span>'
                f'<span class="arrow">·</span>'
                f'<span>Pending senior review</span>'
            )

        notes = rec.get("reviewer_notes")
        notes_html = (
            f'<div class="notes">&ldquo;{notes}&rdquo;</div>' if notes else ""
        )
        cards.append(
            f'<div class="prior-record {cls}">'
            f'  <div class="row1">'
            f'    <span class="app-id">{app_id}</span>'
            f'    <span class="sep">·</span><span>{decided_at}</span>'
            f'    <span class="sep">·</span><span>decision_id={decision_id}</span>'
            f'  </div>'
            f'  <div class="outcome">{outcome}</div>'
            f'  {notes_html}'
            f'</div>'
        )

    return summary + "".join(cards)


def review_card_html(
    action: str, agent_label: str, override_to: str | None, who: str, when: str
) -> str:
    """Replaces the st.success/st.warning banners for reviewer status."""
    if action == "accept":
        body = (
            f"Accepted the agent's recommendation to "
            f"<strong>{agent_label}</strong>."
        )
        return (
            f'<div class="review-card accepted">'
            f'<span class="badge">Accepted</span>'
            f'<div><div class="body">{body}</div>'
            f'<div class="when">{who} &middot; {when}</div></div></div>'
        )
    body = (
        f"Overrode the agent's recommendation "
        f"(<strong>{agent_label}</strong>) and changed the decision to "
        f"<strong>{(override_to or '').upper()}</strong>."
    )
    return (
        f'<div class="review-card overridden">'
        f'<span class="badge">Overridden</span>'
        f'<div><div class="body">{body}</div>'
        f'<div class="when">{who} &middot; {when}</div></div></div>'
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
# Prior triage history at this bank (customer-level memory)
# Surfaced as a dedicated panel above Run triage so the reviewer sees
# the track record before reading the agent's recommendation. Same data
# the agent gets via get_prior_reviews tool call.
# ---------------------------------------------------------------------------
if app:
    prior = get_prior_reviews(app["customer_id"])
    if prior["prior_count"] == 0:
        title = "Prior history at this bank · new customer"
    else:
        title = (
            f"Prior history at this bank · {prior['prior_count']} prior"
            f" · {prior['override_count']} overridden"
        )
    with st.expander(title, expanded=False):
        st.markdown(prior_history_html(prior), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Run the agent and render events live
# ---------------------------------------------------------------------------
if run_button:
    final = None
    # Outer collapsible wrapper. Streamlit forbids nested st.expander,
    # so the tool-call / tool-result rows below are rendered as native
    # HTML <details> elements (styled in _THEME_CSS).
    with st.expander("Agent reasoning", expanded=False):
        with st.spinner("Agent is thinking…"):
            for event in triage_stream(selected_id):
                t = event["type"]
                if t == "turn_start":
                    st.markdown(
                        f'<div class="thinking-turn">Turn {event["turn"]}</div>',
                        unsafe_allow_html=True,
                    )
                elif t == "tool_call":
                    st.markdown(
                        render_tool_event(event["name"], "call", event["args"]),
                        unsafe_allow_html=True,
                    )
                elif t == "tool_result":
                    st.markdown(
                        render_tool_event(event["name"], "result", event["result"]),
                        unsafe_allow_html=True,
                    )
                elif t == "agent_text":
                    st.markdown(
                        f'<div class="thinking-text">'
                        f'{html_lib.escape(event["text"])}</div>',
                        unsafe_allow_html=True,
                    )
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
# Static replay of the Agent reasoning trace, on reruns where we're not
# actively streaming. Without this, the trace expander vanishes the moment
# the user accepts/overrides — even though tool_call_log is already in
# session_state. We reuse the same expander + HTML <details> styling so
# the live view and the replay look identical.
# ---------------------------------------------------------------------------
pending = st.session_state.get("pending_review")
if (
    not run_button
    and pending
    and pending["selected_id"] == selected_id
    and pending.get("tool_call_log")
):
    with st.expander("Agent reasoning", expanded=False):
        for call in pending["tool_call_log"]:
            st.markdown(
                render_tool_event(call["tool"], "call", call.get("args", {})),
                unsafe_allow_html=True,
            )
            st.markdown(
                render_tool_event(call["tool"], "result", call.get("result", {})),
                unsafe_allow_html=True,
            )

# ---------------------------------------------------------------------------
# Agent recommendation + reviewer (Sarah) panel
# Persists across reruns via session_state so that clicking
# Accept / Override does not wipe the displayed decision.
# ---------------------------------------------------------------------------
if pending and pending["selected_id"] == selected_id:
    d = pending["decision_record"]
    decision_id = d["_persisted"]["decision_id"]
    agent_decision = d["decision"]
    verdict = agent_decision.upper()

    # Side-by-side: cobalt-accented AI Analyst on the left, amber-accented
    # Senior Reviewer on the right. Same structural rhythm (stripe +
    # eyebrow + title), different colour family so the "machine
    # pre-screen" and "human sign-off" roles are visually distinct.
    col_agent, col_review = st.columns([1.2, 1], gap="large")

    with col_agent:
        st.markdown(
            '<div class="section-header agent">'
            '<div class="accent-stripe"></div>'
            '<div class="eyebrow">AI Analyst · automated pre-screen</div>'
            '<div class="title">Agent recommendation</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(decision_card_html(agent_decision), unsafe_allow_html=True)

        flags = d.get("risk_flags", []) or []
        st.markdown(f"**Risk flags** ({len(flags)})")
        st.markdown(flag_pills_html(flags), unsafe_allow_html=True)

        st.markdown("**Reasoning**")
        st.write(d["reasoning"])
        st.markdown("**Key evidence**")
        for ev in d.get("key_evidence", []):
            st.markdown(f"- {ev}")

    with col_review:
        st.markdown(
            '<div class="section-header reviewer">'
            '<div class="accent-stripe"></div>'
            '<div class="eyebrow">Senior reviewer · Sarah</div>'
            '<div class="title">Reviewer decision</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        existing_review = get_reviewer_action(decision_id)
        if existing_review:
            st.markdown(
                review_card_html(
                    action=existing_review["action"],
                    agent_label=verdict,
                    override_to=existing_review.get("override_decision"),
                    who=existing_review["reviewed_by"],
                    when=existing_review["reviewed_at"],
                ),
                unsafe_allow_html=True,
            )
            if existing_review.get("notes"):
                st.markdown(f"**Reviewer notes:** {existing_review['notes']}")
        else:
            st.caption(
                "Sarah's call: accept the agent's recommendation, or override "
                "it with a different decision and notes for the audit trail."
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

    # Raw event log spans the full width below both columns — it's
    # admin/audit detail, not part of the decision dialogue.
    with st.expander("Raw event log (all tool calls + results)", expanded=False):
        st.json(pending["tool_call_log"])

# ---------------------------------------------------------------------------
# Polished audit report (Blue Professional template)
# Available once a decision exists for the currently selected application,
# so reviewers and committee members can preview/download a presentation-
# quality artefact instead of paging through Streamlit widgets.
# ---------------------------------------------------------------------------
if pending and pending["selected_id"] == selected_id:
    st.divider()
    st.subheader("Audit report")
    st.caption(
        "A presentation-quality version of this triage, suitable for sharing "
        "with the credit committee. Preview inline, or download a standalone "
        "HTML file."
    )

    d = pending["decision_record"]
    decision_id = d["_persisted"]["decision_id"]
    review_for_report = get_reviewer_action(decision_id)

    report_html = render_report(
        application=app,
        decision=d,
        tool_call_log=pending["tool_call_log"],
        reviewer_action=review_for_report,
    )

    rc1, rc2 = st.columns([1, 1])
    show_report = rc1.toggle(
        "Show inline preview",
        value=False,
        help="Renders the report deck below. Use arrow keys to navigate slides.",
    )
    rc2.download_button(
        "Download report (HTML)",
        data=report_html,
        file_name=f"triage_report_{app['application_id']}_decision_{decision_id}.html",
        mime="text/html",
        use_container_width=True,
    )

    if show_report:
        components.html(report_html, height=720, scrolling=False)

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
