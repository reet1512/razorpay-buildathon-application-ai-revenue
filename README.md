# Razorpay /buildathon — AI Revenue Recovery

**Track 03** · Recovery Agent for failed subscription payments.

## Quick start

```text
cd recovery-agent
# Use system Python 3.12+ or the project helper if present:
# ..\tools\python.cmd -m pip install -r requirements.txt
pip install -r requirements.txt
copy .env.example .env
pytest -q
uvicorn main:app --reload --port 8000
```

- Batch UI: http://127.0.0.1:8000/ui/batch  
- Docs: [`recovery-agent/README.md`](recovery-agent/README.md)  
- Architecture: [`recovery-agent/docs/ARCHITECTURE.md`](recovery-agent/docs/ARCHITECTURE.md)

## Repo layout

| Path | Contents |
|---|---|
| `recovery-agent/` | App (API, AI, eval, gates, UI) |
| `BUILD_PLAN.md` | Idea + schedule |
| `BUILD_TECH.md` | Phase-by-phase tech guide |

**Never commit `.env`.** Use test-mode Razorpay keys only.
