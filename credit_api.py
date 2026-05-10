"""
Mock credit-bureau REST API for the SME Loan Triage demo.

Simulates a third-party credit reference agency (think Experian or Equifax)
exposing a single read endpoint:

    GET /credit-score/{customer_id}

In a real Allica integration this would be an external HTTPS service behind
authentication and rate limits. We hard-code deterministic mock scores so
the demo is reproducible and aligned with the seeded repayment history.

Run the service:
    python credit_api.py

Then in another terminal:
    curl http://localhost:8000/credit-score/CUS001

Interactive docs are auto-generated at:
    http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Mock Credit Bureau API",
    description="Simulated UK credit reference agency for the SME Loan Triage demo.",
    version="1.0.0",
)


class CreditScoreResponse(BaseModel):
    customer_id: str
    credit_score: int        # UK Experian-style score, 0–999
    risk_band: str           # one of: low / medium / high
    on_file_since: str       # ISO date the credit file was opened
    source: str              # bureau name (mocked)


# Hard-coded scores aligned with the repayment profiles in seed.py:
#   strong borrowers → high score, low band
#   weak borrowers   → low score, high band
MOCK_SCORES: dict[str, tuple[int, str, str]] = {
    "CUS001": (920, "low",    "2017-04-12"),  # ABC Bakery — strong, 6y on file
    "CUS002": (885, "low",    "2015-09-03"),  # GreenLeaf — strong, 8y on file
    "CUS003": (720, "medium", "2021-02-18"),  # Pixel Print — medium
    "CUS004": (560, "high",   "2022-06-22"),  # QuickFix — weak, repeated late
    "CUS005": (430, "high",   "2024-01-08"),  # Sunrise Cafe — weak, defaulted
}


@app.get("/", tags=["meta"])
def root():
    """Health check."""
    return {"service": "Mock Credit Bureau API", "status": "ok"}


@app.get(
    "/credit-score/{customer_id}",
    response_model=CreditScoreResponse,
    tags=["credit"],
)
def get_credit_score(customer_id: str) -> CreditScoreResponse:
    """Return a mock credit score for the given customer.

    Returns 404 if the customer has no credit file on record.
    """
    if customer_id not in MOCK_SCORES:
        raise HTTPException(
            status_code=404,
            detail=f"No credit file on record for customer_id={customer_id}",
        )

    score, band, since = MOCK_SCORES[customer_id]
    return CreditScoreResponse(
        customer_id=customer_id,
        credit_score=score,
        risk_band=band,
        on_file_since=since,
        source="MockBureau UK",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("credit_api:app", host="127.0.0.1", port=8000, reload=True)
