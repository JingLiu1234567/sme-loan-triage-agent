"""
SME Loan Triage Agent.

Given an application_id, the agent uses three tools to gather evidence
and produce a final triage decision:

    - query_customer_history  (SQL against bank.db)
    - check_credit_score      (HTTP to mock credit bureau)
    - submit_triage_decision  (writes to the audit log; final step)

The LLM is called via the OpenAI SDK pointed at DeepSeek's
OpenAI-compatible endpoint. Switching to Azure OpenAI later is a
two-line change (api_key + base_url).

Run:
    python agent.py APP001
"""

import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# Force UTF-8 stdout on Windows so £ / € / Chinese print without GBK errors.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from tools import (
    check_credit_score,
    get_application,
    query_customer_history,
    submit_triage_decision,
)

# --------------------------------------------------------------------------
# Client setup
# --------------------------------------------------------------------------
load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not API_KEY:
    sys.exit(
        "ERROR: DEEPSEEK_API_KEY not set.\n"
        "Copy .env.example to .env and fill in your DeepSeek API key."
    )

client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
MODEL = "deepseek-chat"


# --------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# --------------------------------------------------------------------------
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_customer_history",
            "description": (
                "Look up the SME's profile and full repayment history in the "
                "bank's internal database. Returns the customer record, an "
                "aggregated summary (total loans, on_time / late / defaulted "
                "counts, total borrowed), and the raw history rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "Internal customer id, e.g. CUS001",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_credit_score",
            "description": (
                "Call the external credit reference agency (mocked locally) "
                "to retrieve the customer's credit score and risk band."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "Internal customer id, e.g. CUS001",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_triage_decision",
            "description": (
                "Record the FINAL triage decision in the audit log. "
                "Call this exactly once, as your last action. "
                "You MUST cite at least two specific evidence items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "application_id": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["approve", "refer", "decline"],
                        "description": (
                            "approve = clearly low risk; "
                            "refer = ambiguous, send to a senior human reviewer; "
                            "decline = clearly high risk, recommend rejection."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "1-3 sentences justifying the decision.",
                    },
                    "key_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "At least two specific data points supporting the "
                            "decision. EVERY item MUST cite a concrete record "
                            "identifier so an auditor can retrace it: e.g. "
                            "'record_id=18: defaulted, GBP 7,000 due 2025-08-08, "
                            "never paid' or 'credit bureau: score 540, band HIGH'. "
                            "Do NOT use aggregate-only phrasing like '3 of 4 loans "
                            "were late' without naming at least one record_id."
                        ),
                    },
                    "risk_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Short, scannable red-flag tags for the relationship "
                            "manager (e.g. 'Prior default', 'Credit score below 700', "
                            "'2 late payments in last 12m', 'Short bank relationship'). "
                            "Each flag is 2-6 words. Use [] when there are no risks. "
                            "These are visual chips, NOT a restatement of reasoning."
                        ),
                    },
                },
                "required": [
                    "application_id",
                    "decision",
                    "reasoning",
                    "key_evidence",
                    "risk_flags",
                ],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "query_customer_history": query_customer_history,
    "check_credit_score": check_credit_score,
    "submit_triage_decision": submit_triage_decision,
}

SYSTEM_PROMPT = """You are an AI triage analyst at Allica Bank, a UK SME lender.
Your job is to pre-screen a loan application and recommend ONE outcome:

  - approve  : clearly low risk, green light for the relationship manager
  - refer    : evidence is mixed, escalate to a senior human reviewer
  - decline  : clearly high risk, recommend rejection

For every application you MUST:
  1. Call query_customer_history to inspect the SME's profile and repayment record.
  2. Call check_credit_score to retrieve the external credit-bureau score.
  3. Reason carefully about both data sources together.
  4. Call submit_triage_decision exactly once with your final answer.

Decision guidance (heuristics, not rigid rules):
  - Any defaulted loan in history is a strong negative signal; lean 'decline'.
  - 2+ late payments in recent history => lean 'refer' or 'decline'.
  - Credit score < 600 = high band; > 800 = low band.
  - Short relationship + large request relative to revenue = caution.
  - When evidence conflicts, prefer 'refer' over guessing.

You are an analyst, NOT the decision maker. Even when you 'approve', it is a
recommendation only. The relationship manager makes the final call.

Cite at least two specific data points as evidence in submit_triage_decision.
EVERY evidence item MUST name a concrete record identifier from the tool
results so a human auditor can retrace it:
  - For repayment history: cite the `record_id` returned by query_customer_history.
    Example: "record_id=18: defaulted loan, GBP 7,000 due 2025-08-08, never paid".
  - For credit data: cite the bureau payload values (score, band).
    Example: "credit bureau: score 540, band HIGH".
  - For the application itself: cite the `application_id`.
Aggregate stats like "3 of 4 loans were late" are fine ONLY if you also point
to at least one specific record_id as a concrete example.

Also populate `risk_flags` with short scannable red-flag tags (2-6 words each)
that the relationship manager can see at a glance — e.g. "Prior default",
"Credit score below 700", "2 late payments in last 12m", "Short bank
relationship", "Large request vs revenue". Use an empty list ONLY when the
profile is genuinely clean. Risk flags are visual chips for human reviewers,
NOT a paraphrase of the reasoning text."""


# --------------------------------------------------------------------------
# Agent loop — streaming generator
# --------------------------------------------------------------------------
def triage_stream(application_id: str):
    """Yield events as the agent thinks. The last event is `type=final`.

    Event shapes:
        {"type": "application_loaded", "application": {...}}
        {"type": "turn_start",         "turn": int}
        {"type": "tool_call",          "name": str, "args": dict}
        {"type": "tool_result",        "name": str, "result": dict}
        {"type": "agent_text",         "text": str}
        {"type": "error",              "message": str}
        {"type": "final",              "application": {...}, "decision": dict|None,
                                       "tool_call_log": [...], "turns_used": int}
    """
    application = get_application(application_id)
    if application is None:
        yield {"type": "error", "message": f"application {application_id} not found"}
        return

    yield {"type": "application_loaded", "application": application}

    user_message = (
        f"Please triage the following loan application:\n\n"
        f"  application_id  : {application['application_id']}\n"
        f"  customer_id     : {application['customer_id']}\n"
        f"  requested_amount: GBP {application['requested_amount_gbp']:,}\n"
        f"  stated_purpose  : {application['purpose']}\n"
        f"  submitted_at    : {application['submitted_at']}"
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    final_decision: dict[str, Any] | None = None
    tool_call_log: list[dict[str, Any]] = []
    turn = 0

    for turn in range(1, 11):  # safety cap on turns
        yield {"type": "turn_start", "turn": turn}

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        assistant_turn: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if not msg.tool_calls:
            if msg.content:
                yield {"type": "agent_text", "text": msg.content}
            break

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            yield {"type": "tool_call", "name": name, "args": args}

            if name not in TOOL_FUNCTIONS:
                result: dict[str, Any] = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = TOOL_FUNCTIONS[name](**args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}

            tool_call_log.append({"tool": name, "args": args, "result": result})
            yield {"type": "tool_result", "name": name, "result": result}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                }
            )

            if name == "submit_triage_decision":
                final_decision = {**args, "_persisted": result}

        if final_decision is not None:
            break

    yield {
        "type": "final",
        "application": application,
        "decision": final_decision,
        "tool_call_log": tool_call_log,
        "turns_used": turn,
    }


def triage(application_id: str, verbose: bool = True) -> dict[str, Any]:
    """Synchronous wrapper around `triage_stream` for CLI use.

    Consumes the event stream, optionally prints, and returns the final dict.
    """
    final_event: dict[str, Any] | None = None
    for event in triage_stream(application_id):
        if verbose:
            t = event["type"]
            if t == "turn_start":
                print(f"\n--- turn {event['turn']} ---")
            elif t == "tool_call":
                print(f"[tool call] {event['name']}({event['args']})")
            elif t == "tool_result":
                snippet = json.dumps(event["result"], default=str)[:160]
                print(f"[tool result] {snippet}{'...' if len(snippet) == 160 else ''}")
            elif t == "agent_text":
                print(f"[agent text] {event['text']}")
            elif t == "error":
                print(f"[ERROR] {event['message']}")
        if event["type"] == "final":
            final_event = event

    return final_event or {"error": "no final event"}


# --------------------------------------------------------------------------
# CLI entry
# --------------------------------------------------------------------------
if __name__ == "__main__":
    app_id = sys.argv[1] if len(sys.argv) > 1 else "APP001"
    out = triage(app_id, verbose=True)

    print("\n" + "=" * 60)
    print("FINAL DECISION")
    print("=" * 60)
    if out.get("final_decision"):
        print(json.dumps(out["final_decision"], indent=2, ensure_ascii=False))
    else:
        print("(no final decision produced)")
        print(out)
