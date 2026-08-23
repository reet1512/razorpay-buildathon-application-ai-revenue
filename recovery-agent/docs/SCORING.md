# Scoring / reward definition (evaluation)

This document freezes what “winning” means in the Recovery Agent eval harness.
**Do not silently change these formulas** without updating this file and calling
it out in the PR.

## Winner (primary)

**Winner = higher `net_recovered_inr`.**

```text
net = gross_recovered_inr - total_cost_inr
total_cost = attempt_cost + mdr_cost + risk_cost + customer_cost
delta_net = ours.net_recovered_inr - b2.net_recovered_inr
winner = ours if delta_net > 0 else b2 if delta_net < 0 else tie
```

All cost rates live in `config/costs.json` and are loaded via `config/costs.py`.
Computed in `eval/costing.py` and aggregated in `eval/metrics.py`.

### Gross recovered (secondary, always shown)

```text
delta_gross = ours.gross_recovered_inr - b2.gross_recovered_inr
```

B2 may beat us on gross while we win on net — show both.

### What counts as recovered (gross)

- Simulator plays each policy’s planned actions against hidden payer truth
  (`eval/simulate.py` + `eval/payer_model.py`).
- On first successful retry/contact (or natural recovery for empty plans),
  the case contributes `amount_paise` to gross recovered.
- `gross_recovered_inr = sum(recovered_paise) / 100`
- `recovery_rate = gross_recovered_inr / at_risk_inr`

### Cost components

| Component | Source |
|---|---|
| Attempt cost | Retries (PSP fee + excess penalty past scheme cap) + contacts (SMS / WhatsApp / email rates) |
| MDR | `success.mdr_pct × gross_recovered_inr` |
| Risk cost | Support/chargeback/decay assumptions on inappropriate PROHIBITED contact and excess attempts |
| Customer cost | `churn_prob × ltv` on inappropriate contacts |

### Other batch fields

| Field | Meaning |
|---|---|
| `wasted_attempts` | Retries against `CUSTOMER_ACTION` (structurally zero recovery) |
| `scheme_cap_breaches` | Cases where retries exceed `scheme_limits.max_attempts_per_transaction_30d` |
| `forgone_recovery_inr` | Expected recovery refused on `PROHIBITED` (ours only; compliance cost, not a loss) |
| `cost_per_rupee_recovered` | `total_cost_inr / gross_recovered_inr` |

## Headline benchmark

| Knob | Canonical value | Notes |
|---|---|---|
| Seed | **42** | Fixed reference; changing seed ≠ better model |
| N | 200 (UI) / 500–1000 (CLI) | Larger N = less sampling noise, not a better policy |

Multi-seed reports exist to **avoid cherry-picking** a lucky seed.

## Why B2 can win gross but lose net

B2 schedules three retries plus one generic nag on **every** failure reason.
On `CUSTOMER_ACTION` failures, retries are structurally wasted (zero recovery
probability) but still priced. Net scoreboard makes that visible.
