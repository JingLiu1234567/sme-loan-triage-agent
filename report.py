"""
Audit-report renderer.

Takes the triage result (application + agent decision + tool_call_log)
and the optional reviewer action, and produces a self-contained HTML
audit report styled after the `Blue Professional` template from
github.com/zarazhangrui/beautiful-html-templates.

The report is a 6-slide deck: Cover -> Decision Summary -> Customer
Profile -> Reasoning -> Reviewer Decision -> Closing. A Prior-Reviews
slide is inserted before Reviewer Decision iff prior history exists.

Render with `render_report(...)` which returns a full HTML document
string. Embed in Streamlit via `st.components.v1.html(html, height=…,
scrolling=False)` or write to a `.html` file for download.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Iterable

DECISION_LABELS = {
    "approve": "Approve",
    "refer":   "Refer to Senior Reviewer",
    "decline": "Decline",
}


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------
def _h(value: Any) -> str:
    """HTML-escape any value for safe interpolation into the template."""
    return html.escape("" if value is None else str(value), quote=True)


def _gbp(amount: Any) -> str:
    try:
        return f"GBP {int(amount):,}"
    except (TypeError, ValueError):
        return _h(amount)


def _date(value: Any) -> str:
    """Best-effort prettifier for ISO timestamps; falls back to raw string."""
    if not value:
        return ""
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.split(".")[0], fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return _h(s)


def _find_tool(tool_call_log: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the latest result dict for a given tool name from the log."""
    matches = [c for c in tool_call_log if c.get("tool") == name]
    return matches[-1]["result"] if matches else None


def _resolve_final_decision(
    agent_decision: str, reviewer_action: dict[str, Any] | None
) -> tuple[str, str]:
    """Return (final_decision_key, status_label) for the summary card."""
    if not reviewer_action:
        return agent_decision, "Pending Review"
    if reviewer_action.get("action") == "accept":
        return agent_decision, "Accepted"
    if reviewer_action.get("action") == "override":
        return reviewer_action.get("override_decision") or agent_decision, "Overridden"
    return agent_decision, "Pending Review"


# ---------------------------------------------------------------------------
# Slide builders — each returns one <div class="slide ..."> string
# ---------------------------------------------------------------------------
def _slide_cover(
    *,
    application: dict[str, Any],
    decision: dict[str, Any],
    customer: dict[str, Any] | None,
    final_key: str,
    status_label: str,
    generated_at: str,
) -> str:
    customer_name = (customer or {}).get("business_name") or application["customer_id"]
    return f"""
    <div class="slide layout-cover active">
      <div class="cover-decoration"></div>
      <div class="cover-dots">
        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
        <div class="dot"></div><div class="dot"></div><div class="dot"></div>
      </div>
      <div class="accent-line"></div>
      <h1>SME Loan Triage<br>Audit Report</h1>
      <p class="subtitle">
        Application <strong>{_h(application['application_id'])}</strong> &middot;
        {_h(customer_name)} &middot;
        Requested {_gbp(application['requested_amount_gbp'])}
      </p>
      <p class="meta">
        Decision: <strong>{_h(DECISION_LABELS.get(final_key, final_key).upper())}</strong>
        &nbsp;&middot;&nbsp; {_h(status_label)}
        &nbsp;&middot;&nbsp; Generated {_h(generated_at)}
        &nbsp;&middot;&nbsp; Confidential
      </p>
    </div>
    """


def _slide_decision_summary(
    *,
    agent_decision: str,
    reviewer_action: dict[str, Any] | None,
    risk_flags: list[str],
    final_key: str,
    status_label: str,
    decision_id: Any,
) -> str:
    agent_label = DECISION_LABELS.get(agent_decision, agent_decision).upper()
    final_label = DECISION_LABELS.get(final_key, final_key).upper()

    if reviewer_action is None:
        review_card_value = "—"
        review_card_label = "Pending Senior Reviewer"
        review_card_desc = "The relationship manager has not yet responded to the agent's recommendation."
        review_supports: list[str] = []
        review_change_cls = "negative"
        review_change = "Awaiting human sign-off"
    elif reviewer_action.get("action") == "accept":
        review_card_value = "Accepted"
        review_card_label = "Senior reviewer endorsed agent"
        review_card_desc = "The relationship manager accepted the agent's recommendation without modification."
        review_supports = [
            f"Reviewed by {reviewer_action.get('reviewed_by') or 'reviewer'}",
            f"Reviewed at {_date(reviewer_action.get('reviewed_at'))}",
        ]
        review_change_cls = "positive"
        review_change = "Agent + human aligned"
    else:
        override_to = DECISION_LABELS.get(
            reviewer_action.get("override_decision") or "", ""
        ).upper() or "—"
        review_card_value = "Overridden"
        review_card_label = f"Reviewer changed to {override_to}"
        review_card_desc = (
            "The relationship manager overrode the agent's recommendation. "
            "Notes captured below for audit."
        )
        review_supports = [
            f"Reviewed by {reviewer_action.get('reviewed_by') or 'reviewer'}",
            f"Reviewed at {_date(reviewer_action.get('reviewed_at'))}",
        ]
        review_change_cls = "negative"
        review_change = "Agent recommendation overridden"

    risk_supports = [f"{f}" for f in risk_flags[:4]] or [
        "No risk flags raised on this application"
    ]
    risk_change_cls = "negative" if risk_flags else "positive"
    risk_change = (
        f"{len(risk_flags)} red-flag tag{'s' if len(risk_flags) != 1 else ''}"
        if risk_flags
        else "Profile is clean"
    )

    return f"""
    <div class="slide layout-metrics">
      <div class="slide-header">
        <h4>Decision Summary</h4>
        <span class="tag">Audit Record #{_h(decision_id)}</span>
      </div>
      <div class="slide-content">
        <h2>Final outcome: <span style="color:var(--primary);">{_h(final_label)}</span> &middot; {_h(status_label)}</h2>
        <div class="metrics-row">
          <div class="metric-card">
            <div class="metric-value" style="font-size:clamp(1.6rem,2.4vw,2.1rem);">{_h(agent_label)}</div>
            <div class="metric-label">Agent recommendation</div>
            <div class="metric-desc">The AI triage analyst's automated pre-screen, based on internal repayment history, external credit-bureau data, and prior reviewer feedback for this customer.</div>
          </div>
          <div class="metric-card">
            <div class="metric-value" style="font-size:clamp(1.6rem,2.4vw,2.1rem);">{_h(review_card_value)}</div>
            <div class="metric-label">{_h(review_card_label)}</div>
            <div class="metric-desc">{_h(review_card_desc)}</div>
            <ul class="metric-supports">
              {"".join(f"<li>{_h(s)}</li>" for s in review_supports)}
            </ul>
            <div class="metric-change {review_change_cls}">
              <span>&middot;</span> {_h(review_change)}
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-value">{len(risk_flags)}</div>
            <div class="metric-label">Risk flags raised</div>
            <div class="metric-desc">Short scannable red-flag tags surfaced by the agent for relationship-manager triage.</div>
            <ul class="metric-supports">
              {"".join(f"<li>{_h(s)}</li>" for s in risk_supports)}
            </ul>
            <div class="metric-change {risk_change_cls}">
              <span>&middot;</span> {_h(risk_change)}
            </div>
          </div>
        </div>
      </div>
    </div>
    """


def _slide_profile(
    *,
    application: dict[str, Any],
    customer: dict[str, Any] | None,
    summary: dict[str, Any] | None,
    credit: dict[str, Any] | None,
) -> str:
    customer = customer or {}
    summary = summary or {}
    credit = credit or {}

    on_time = summary.get("on_time") or 0
    total_loans = summary.get("total_loans") or 0
    on_time_rate = (
        f"{round(100 * on_time / total_loans)}%" if total_loans else "—"
    )
    defaulted = summary.get("defaulted") or 0
    late = summary.get("late") or 0
    score = credit.get("score") or "—"
    band = (credit.get("band") or credit.get("risk_band") or "—").upper() if isinstance(
        credit.get("band") or credit.get("risk_band"), str
    ) else "—"

    cells = [
        (_gbp(application['requested_amount_gbp']), "this application", "Requested loan amount", _h(application.get("purpose", ""))),
        (_h(customer.get("industry") or customer.get("sector") or "—"), "sector", "Industry", _h(customer.get("business_name") or application["customer_id"])),
        (_h(customer.get("years_in_business") or customer.get("years") or "—"), "years", "Time in business", "Length of operating history on file"),
        (str(score), "credit score", "External credit bureau", f"Risk band: {_h(band)}"),
        (str(total_loans), "loans on file", "Prior repayment history", f"{on_time} on-time &middot; {late} late &middot; {defaulted} defaulted"),
        (on_time_rate, "on-time rate", "Repayment track record", "Share of past loans paid on or before the due date"),
    ]

    def render_cell(num: str, unit: str, name: str, ctx: str) -> str:
        return f"""
          <div class="stat-cell">
            <div class="stat-top">
              <span class="stat-num">{num}</span>
              <span class="stat-unit">{unit}</span>
            </div>
            <div class="stat-name">{name}</div>
            <div class="stat-context">{ctx}</div>
          </div>
        """

    return f"""
    <div class="slide layout-dashboard">
      <div class="slide-header">
        <h4>Customer Profile</h4>
        <span class="tag">{_h(application['customer_id'])}</span>
      </div>
      <div class="slide-content">
        <h2>Profile and history at a glance</h2>
        <div class="stats-grid">
          {"".join(render_cell(*c) for c in cells)}
        </div>
      </div>
    </div>
    """


def _slide_reasoning(*, decision: dict[str, Any]) -> str:
    reasoning = decision.get("reasoning") or ""
    evidence = decision.get("key_evidence") or []
    flags = decision.get("risk_flags") or []

    flag_chips = "".join(
        f'<span class="tag" style="margin-right:.4rem;margin-bottom:.4rem;display:inline-block;">{_h(f)}</span>'
        for f in flags
    ) or '<span class="tag" style="background:rgba(5,150,105,0.1);color:#059669;">No risk flags</span>'

    evidence_items = "".join(
        f'<li><span class="num">{i + 1:02d}</span><div><p>{_h(ev)}</p></div></li>'
        for i, ev in enumerate(evidence)
    ) or "<li><div><p>No evidence cited.</p></div></li>"

    return f"""
    <div class="slide layout-split">
      <div class="slide-header">
        <h4>Agent Reasoning &amp; Evidence</h4>
        <span class="tag">Analysis</span>
      </div>
      <div class="slide-content">
        <h2>Why the agent reached this recommendation</h2>
        <div class="split-body">
          <div class="split-left">
            <h3 style="margin-bottom:.6rem;">Reasoning</h3>
            <p style="font-size:clamp(.95rem,1.2vw,1.1rem);color:var(--text);line-height:1.6;">
              {_h(reasoning)}
            </p>
            <h3 style="margin-top:1.6rem;margin-bottom:.6rem;">Risk flags</h3>
            <div>{flag_chips}</div>
          </div>
          <div class="split-right">
            <h3 style="margin-bottom:.6rem;">Key evidence cited</h3>
            <ol class="insight-list" style="list-style:none;padding:0;display:flex;flex-direction:column;gap:.9rem;">
              {evidence_items}
            </ol>
          </div>
        </div>
      </div>
    </div>
    """


def _slide_prior_reviews(*, prior: dict[str, Any]) -> str:
    history = prior.get("history") or []

    def step(i: int, item: dict[str, Any]) -> str:
        agent = (item.get("agent_decision") or "").upper()
        action = item.get("reviewer_action") or "pending"
        if action == "override":
            final = (item.get("override_decision") or "").upper()
            outcome = f"Agent: {agent} &rarr; Reviewer overrode to {final}"
        elif action == "accept":
            outcome = f"Agent: {agent} &middot; Reviewer accepted"
        else:
            outcome = f"Agent: {agent} &middot; Pending review"

        notes = item.get("reviewer_notes")
        notes_html = (
            f'<div class="step-desc" style="margin-top:.4rem;font-style:italic;">&ldquo;{_h(notes)}&rdquo;</div>'
            if notes else ""
        )
        return f"""
          <div class="timeline-step">
            <div class="step-circle">{i + 1}</div>
            <div class="step-title">{_h(item.get('application_id', ''))} &middot; {_date(item.get('decided_at'))}</div>
            <div class="step-desc">{outcome}</div>
            {notes_html}
          </div>
        """

    steps_html = "".join(step(i, h) for i, h in enumerate(history[:4]))
    return f"""
    <div class="slide layout-timeline">
      <div class="slide-header">
        <h4>Prior Triage History</h4>
        <span class="tag">{prior.get('prior_count', 0)} prior &middot; {prior.get('override_count', 0)} overridden</span>
      </div>
      <div class="slide-content">
        <h2>What happened the last time this customer applied</h2>
        <div class="timeline-track">
          {steps_html}
        </div>
      </div>
    </div>
    """


def _slide_reviewer(*, reviewer_action: dict[str, Any] | None, agent_decision: str) -> str:
    if reviewer_action is None:
        quote = (
            "Awaiting senior reviewer sign-off. The agent's recommendation has been "
            "logged to the audit trail but no human decision has been recorded yet."
        )
        source = "Pending &mdash; Senior Relationship Manager"
    elif reviewer_action.get("action") == "accept":
        agent_label = DECISION_LABELS.get(agent_decision, agent_decision).upper()
        quote = (
            f"Accepted the agent's recommendation to {agent_label}. The automated "
            f"triage aligned with my own assessment of this application."
        )
        source = (
            f"<strong>{_h(reviewer_action.get('reviewed_by') or 'Senior Reviewer')}</strong> "
            f"&mdash; {_date(reviewer_action.get('reviewed_at'))}"
        )
    else:
        notes = reviewer_action.get("notes") or "No notes provided."
        quote = notes
        override_to = DECISION_LABELS.get(
            reviewer_action.get("override_decision") or "", ""
        ).upper()
        source = (
            f"<strong>{_h(reviewer_action.get('reviewed_by') or 'Senior Reviewer')}</strong> "
            f"&mdash; Overrode to {_h(override_to)} on {_date(reviewer_action.get('reviewed_at'))}"
        )

    return f"""
    <div class="slide layout-quote">
      <div class="quote-decoration"></div>
      <div class="quote-decoration-2"></div>
      <div class="quote-mark">&ldquo;</div>
      <blockquote>{_h(quote) if reviewer_action and reviewer_action.get('action') == 'override' else quote}</blockquote>
      <p class="quote-source">{source}</p>
    </div>
    """


def _slide_closing(
    *,
    decision_id: Any,
    decided_at: Any,
    reviewer_action: dict[str, Any] | None,
    application_id: str,
) -> str:
    rows = [
        ("Application", _h(application_id)),
        ("Decision ID", _h(decision_id)),
        ("Agent decided at", _date(decided_at)),
    ]
    if reviewer_action:
        rows.append(
            (
                f"Reviewer {reviewer_action.get('action') or ''}".strip().title(),
                _date(reviewer_action.get("reviewed_at")),
            )
        )
    audit_lines = "".join(
        f'<p class="closing-contact" style="margin-top:.2rem;">{label}: <strong>{value}</strong></p>'
        for label, value in rows
    )
    return f"""
    <div class="slide layout-closing">
      <div class="closing-decoration"></div>
      <div class="closing-decoration-2"></div>
      <div class="accent-line" style="margin: 0 auto 1.5rem;"></div>
      <h1>End of Report</h1>
      <p class="closing-sub">
        This document is an immutable audit record. The agent recommendation,
        the senior reviewer's response, and all supporting evidence are
        retained for compliance and governance review.
      </p>
      {audit_lines}
    </div>
    """


# ---------------------------------------------------------------------------
# Master CSS — adapted from the Blue Professional template
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --bg: #fdfae7;
  --primary: #1e2bfa;
  --text: #111111;
  --text-muted: #6b6b6b;
  --text-light: #9a9a9a;
  --accent-light: rgba(30, 43, 250, 0.08);
  --accent-medium: rgba(30, 43, 250, 0.15);
  --border: rgba(30, 43, 250, 0.2);
  --card-bg: rgba(30, 43, 250, 0.04);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 100%; height: 100%; overflow: hidden;
  font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); }
.deck { width: 100vw; height: 100vh; position: relative; overflow: hidden; }
.slide { position: absolute; top: 0; left: 0; width: 100vw; height: 100vh;
  display: flex; flex-direction: column; padding: 3.5vw 4vw 8.5vh 4vw;
  opacity: 0; pointer-events: none; transform: translateX(40px);
  transition: opacity .5s ease, transform .5s ease; overflow: hidden; }
.slide.active { opacity: 1; pointer-events: all; transform: translateX(0); z-index: 10; }
.slide.prev { transform: translateX(-40px); }
h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif; font-weight: 600;
  line-height: 1.1; letter-spacing: -0.02em; }
h1 { font-size: clamp(2.4rem, 4.4vw, 3.8rem); font-weight: 700; }
h2 { font-size: clamp(1.6rem, 2.6vw, 2.3rem); margin-bottom: 1.2rem; }
h3 { font-size: clamp(1rem, 1.6vw, 1.3rem); font-weight: 500; line-height: 1.3; }
h4 { font-size: clamp(.85rem, 1.2vw, 1rem); font-weight: 600;
  text-transform: uppercase; letter-spacing: .08em; color: var(--primary); }
p, li { font-size: clamp(.85rem, 1.1vw, 1.05rem); line-height: 1.6; color: var(--text-muted); }
blockquote { font-family: 'Space Grotesk', sans-serif; font-weight: 500;
  font-size: clamp(1.4rem, 2.6vw, 2.2rem); line-height: 1.3; color: var(--text);
  max-width: 70vw; margin: 1.5rem auto; letter-spacing: -0.01em; }
.slide-header { display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 2.5vh; flex-shrink: 0; }
.slide-header h4 { margin: 0; }
.slide-header .tag, .tag { font-family: 'Space Grotesk', sans-serif; font-size: .75rem;
  font-weight: 500; color: var(--primary); background: var(--accent-light);
  padding: .35rem .9rem; border-radius: 100px; }
.slide-content { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.nav-controls { position: fixed; bottom: 2.5vh; right: 3vw; display: flex;
  align-items: center; gap: .8rem; z-index: 100; }
.nav-btn { width: 44px; height: 44px; border-radius: 50%; border: 1.5px solid var(--border);
  background: var(--bg); color: var(--primary); cursor: pointer; display: flex;
  align-items: center; justify-content: center; transition: all .2s ease; font-size: 1.1rem; }
.nav-btn:hover { background: var(--primary); color: var(--bg); border-color: var(--primary); }
.nav-btn:disabled { opacity: .3; cursor: not-allowed; }
.slide-counter { font-family: 'Space Grotesk', sans-serif; font-size: .8rem; font-weight: 500;
  color: var(--text-muted); letter-spacing: .05em; position: fixed; bottom: 2.5vh; left: 3vw; z-index: 100; }
.progress-bar { position: fixed; bottom: 0; left: 0; height: 3px;
  background: var(--primary); transition: width .4s ease; z-index: 100; }
.accent-line { width: 60px; height: 4px; background: var(--primary); border-radius: 2px; margin-bottom: 1.5rem; }

/* Cover */
.layout-cover { justify-content: center; align-items: flex-start; padding-left: 8vw; }
.layout-cover h1 { max-width: 60vw; margin-bottom: 1.5rem; line-height: 1.05; }
.layout-cover .subtitle { font-size: clamp(1rem, 1.5vw, 1.25rem); color: var(--text-muted);
  max-width: 50vw; margin-bottom: 3rem; font-weight: 400; }
.layout-cover .meta { font-family: 'Space Grotesk', sans-serif; font-size: .85rem;
  color: var(--text-light); letter-spacing: .05em; }
.layout-cover .cover-decoration { position: absolute; top: 0; right: 0; width: 35vw; height: 100vh;
  background: var(--accent-light); clip-path: polygon(30% 0, 100% 0, 100% 100%, 0% 100%); }
.layout-cover .cover-dots { position: absolute; bottom: 12vh; right: 8vw; display: grid;
  grid-template-columns: repeat(3, 1fr); gap: 12px; opacity: .25; }
.layout-cover .cover-dots .dot { width: 6px; height: 6px; background: var(--primary); border-radius: 50%; }

/* Metrics */
.layout-metrics .slide-content { justify-content: flex-start; }
.layout-metrics .metrics-row { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem; margin-top: .5rem; align-items: stretch; }
.metric-card { display: flex; flex-direction: column; gap: .7rem; padding: 1.5rem 1.6rem;
  border-radius: 14px; border: 1.5px solid var(--border); background: var(--card-bg); }
.metric-card .metric-value { font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(2.2rem, 3.4vw, 3rem); font-weight: 700; color: var(--primary); line-height: 1; }
.metric-card .metric-label { font-size: clamp(.95rem, 1.3vw, 1.1rem); font-weight: 600;
  color: var(--text); line-height: 1.3; }
.metric-card .metric-desc { font-size: clamp(.78rem, .95vw, .9rem); color: var(--text-muted); line-height: 1.5; }
.metric-card .metric-supports { list-style: none; display: flex; flex-direction: column;
  gap: .45rem; margin: .2rem 0 0; padding: .7rem 0 0; border-top: 1px solid var(--border); }
.metric-card .metric-supports li { font-size: clamp(.75rem, .9vw, .85rem); color: var(--text-muted);
  padding-left: 1rem; position: relative; line-height: 1.45; }
.metric-card .metric-supports li::before { content: '—'; position: absolute; left: 0; color: var(--text-light); }
.metric-card .metric-change { display: inline-flex; align-items: center; gap: .3rem;
  font-family: 'Space Grotesk', sans-serif; font-size: .78rem; font-weight: 600; margin-top: .3rem; }
.metric-change.positive { color: #059669; }
.metric-change.negative { color: #dc2626; }

/* Dashboard */
.layout-dashboard .slide-content { justify-content: flex-start; }
.layout-dashboard .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.2rem; margin-top: .5rem; }
.stat-cell { display: flex; flex-direction: column; gap: .5rem; padding: 1.4rem 1.5rem;
  border-radius: 12px; background: var(--card-bg); border: 1px solid var(--border); }
.stat-cell .stat-top { display: flex; align-items: baseline; gap: .5rem; }
.stat-cell .stat-num { font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(1.6rem, 2.4vw, 2.1rem); font-weight: 700; color: var(--primary); line-height: 1; }
.stat-cell .stat-unit { font-size: .8rem; color: var(--text-light); font-weight: 500; }
.stat-cell .stat-name { font-size: clamp(.85rem, 1vw, .95rem); color: var(--text); line-height: 1.35; font-weight: 500; }
.stat-cell .stat-context { font-size: .75rem; color: var(--text-light); line-height: 1.4;
  padding-top: .4rem; border-top: 1px solid var(--border); }

/* Split */
.layout-split .slide-content { justify-content: flex-start; }
.layout-split .split-body { display: grid; grid-template-columns: 1.05fr 1fr; gap: 3.5rem; margin-top: .5rem; }
.split-left, .split-right { display: flex; flex-direction: column; gap: 1.4rem; }
.split-right { padding-left: 2.5rem; border-left: 2px solid var(--border); }
.insight-list li { display: flex; gap: 1rem; align-items: flex-start; }
.insight-list li .num { font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem;
  font-weight: 700; color: var(--primary); min-width: 30px; line-height: 1.6; }
.insight-list li p { color: var(--text); font-size: clamp(.85rem, 1.05vw, 1rem); line-height: 1.55; }

/* Timeline */
.layout-timeline .slide-content { justify-content: flex-start; }
.layout-timeline .timeline-track { display: grid; grid-auto-flow: column;
  grid-auto-columns: 1fr; gap: 1.2rem; margin-top: 1.2rem; }
.timeline-step { display: flex; flex-direction: column; gap: .5rem; padding: 1.2rem;
  border-radius: 12px; background: var(--card-bg); border: 1px solid var(--border); }
.step-circle { width: 36px; height: 36px; border-radius: 50%; background: var(--primary);
  color: var(--bg); display: flex; align-items: center; justify-content: center;
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; }
.step-title { font-family: 'Space Grotesk', sans-serif; font-weight: 600;
  font-size: clamp(.9rem, 1.1vw, 1rem); color: var(--text); margin-top: .4rem; }
.step-desc { font-size: clamp(.78rem, .95vw, .88rem); color: var(--text-muted); line-height: 1.5; }

/* Quote */
.layout-quote { align-items: center; justify-content: center; text-align: center; padding: 4vh 8vw; }
.layout-quote .quote-mark { font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(5rem, 9vw, 8rem); font-weight: 700; color: var(--primary);
  line-height: .8; opacity: .5; margin-bottom: -1rem; }
.layout-quote blockquote { font-style: normal; }
.layout-quote .quote-source { font-family: 'Space Grotesk', sans-serif; font-size: .9rem;
  color: var(--text-muted); margin-top: 1.5rem; letter-spacing: .02em; }
.layout-quote .quote-decoration { position: absolute; top: 10vh; left: 5vw;
  width: 60px; height: 60px; border: 2px solid var(--border); border-radius: 50%; opacity: .4; }
.layout-quote .quote-decoration-2 { position: absolute; bottom: 15vh; right: 8vw;
  width: 40px; height: 40px; background: var(--accent-light); border-radius: 50%; }

/* Closing */
.layout-closing { align-items: center; justify-content: center; text-align: center; padding: 4vh 8vw; }
.layout-closing h1 { margin-bottom: 1.5rem; }
.layout-closing .closing-sub { max-width: 50vw; margin: 0 auto 2.5rem; font-size: 1.1rem; color: var(--text-muted); }
.layout-closing .closing-contact { font-family: 'Space Grotesk', sans-serif;
  font-size: .85rem; color: var(--text-light); margin-top: .5rem; letter-spacing: .03em; }
.layout-closing .closing-decoration { position: absolute; top: 8vh; left: 8vw;
  width: 80px; height: 80px; border: 2px solid var(--border); border-radius: 50%; opacity: .4; }
.layout-closing .closing-decoration-2 { position: absolute; bottom: 10vh; right: 10vw;
  width: 60px; height: 60px; background: var(--accent-light); border-radius: 50%; }
"""

_JS = """
const slides = document.querySelectorAll('.slide');
const currentEl = document.getElementById('current');
const totalEl = document.getElementById('total');
const progressEl = document.getElementById('progress');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
let current = 0;
const total = slides.length;
totalEl.textContent = total;
function updateSlide() {
  slides.forEach((slide, i) => {
    slide.classList.remove('active', 'prev');
    if (i === current) slide.classList.add('active');
    else if (i < current) slide.classList.add('prev');
  });
  currentEl.textContent = current + 1;
  progressEl.style.width = ((current + 1) / total * 100) + '%';
  prevBtn.disabled = current === 0;
  nextBtn.disabled = current === total - 1;
}
function changeSlide(dir) {
  const next = current + dir;
  if (next >= 0 && next < total) { current = next; updateSlide(); }
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); changeSlide(1); }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); changeSlide(-1); }
  else if (e.key === 'Home') { e.preventDefault(); current = 0; updateSlide(); }
  else if (e.key === 'End') { e.preventDefault(); current = total - 1; updateSlide(); }
});
let touchStartX = 0;
document.addEventListener('touchstart', (e) => { touchStartX = e.changedTouches[0].screenX; }, { passive: true });
document.addEventListener('touchend', (e) => {
  const diff = touchStartX - e.changedTouches[0].screenX;
  if (Math.abs(diff) > 50) changeSlide(diff > 0 ? 1 : -1);
}, { passive: true });
updateSlide();
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_report(
    application: dict[str, Any],
    decision: dict[str, Any],
    tool_call_log: list[dict[str, Any]],
    reviewer_action: dict[str, Any] | None = None,
) -> str:
    """Render the full HTML audit-report deck.

    Args:
        application: dict from get_application — application_id, customer_id,
            requested_amount_gbp, purpose, submitted_at.
        decision: dict from submit_triage_decision — decision, reasoning,
            key_evidence, risk_flags, and _persisted (with decision_id).
        tool_call_log: the agent's tool_call_log; we extract the latest
            query_customer_history / check_credit_score / get_prior_reviews
            results from it.
        reviewer_action: optional dict from get_reviewer_action — action,
            override_decision, notes, reviewed_at, reviewed_by.
    """
    history_result = _find_tool(tool_call_log, "query_customer_history") or {}
    credit_result = _find_tool(tool_call_log, "check_credit_score") or {}
    prior_result = _find_tool(tool_call_log, "get_prior_reviews") or {}

    customer = history_result.get("customer")
    summary = history_result.get("summary")

    agent_decision = decision.get("decision", "refer")
    final_key, status_label = _resolve_final_decision(agent_decision, reviewer_action)
    decision_id = (decision.get("_persisted") or {}).get("decision_id", "—")
    decided_at = (decision.get("_persisted") or {}).get("decided_at") or datetime.now()
    generated_at = datetime.now().strftime("%d %b %Y")

    slides: list[str] = [
        _slide_cover(
            application=application,
            decision=decision,
            customer=customer,
            final_key=final_key,
            status_label=status_label,
            generated_at=generated_at,
        ),
        _slide_decision_summary(
            agent_decision=agent_decision,
            reviewer_action=reviewer_action,
            risk_flags=decision.get("risk_flags") or [],
            final_key=final_key,
            status_label=status_label,
            decision_id=decision_id,
        ),
        _slide_profile(
            application=application,
            customer=customer,
            summary=summary,
            credit=credit_result,
        ),
        _slide_reasoning(decision=decision),
    ]
    if prior_result.get("history"):
        slides.append(_slide_prior_reviews(prior=prior_result))
    slides.append(
        _slide_reviewer(reviewer_action=reviewer_action, agent_decision=agent_decision)
    )
    slides.append(
        _slide_closing(
            decision_id=decision_id,
            decided_at=decided_at,
            reviewer_action=reviewer_action,
            application_id=application["application_id"],
        )
    )

    nav_html = """
    <div class="slide-counter"><span id="current">1</span> / <span id="total">1</span></div>
    <div class="progress-bar" id="progress"></div>
    <div class="nav-controls">
      <button class="nav-btn" id="prevBtn" onclick="changeSlide(-1)" aria-label="Previous slide">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
      </button>
      <button class="nav-btn" id="nextBtn" onclick="changeSlide(1)" aria-label="Next slide">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
      </button>
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SME Loan Triage Audit Report &middot; {_h(application['application_id'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="deck">
{"".join(slides)}
</div>
{nav_html}
<script>{_JS}</script>
</body>
</html>"""
