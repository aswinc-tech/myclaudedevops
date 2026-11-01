# tatkal-agent

An agentic Tatkal booking assistant. Claude plans the booking, MCP tools do the work, a human
approves every commitment, and a deterministic executor handles the timing and retries at
window-open, where milliseconds count.

> **Scope.** This project books only through an *authorised* backend (an IRCTC partner / B2B
> integration). It ships no screen-scraper, no CAPTCHA solver and no multi-account tricks. Bots
> like that are what make Tatkal unfair for everyone else, and IRCTC blocks the accounts that use
> them. See [docs/COMPLIANCE.md](docs/COMPLIANCE.md). Until you plug in a partner API, the app runs
> against a realistic simulator.

## Why it is built this way

The full list of user problems, with sources, is in [docs/RESEARCH.md](docs/RESEARCH.md).

| User pain (from reviews/news) | Design response |
|---|---|
| Site hangs / 503s right at 10:00 | Deadline-aware retry with decorrelated jitter (`retry.py`). No LLM round-trips in the hot path. |
| "Seats vanish while I'm still typing" | Everything is decided and approved **before** the window. Passengers come from a pre-filled profile, payment method is pre-selected. |
| Losing the race by seconds | Clock synced to the booking server's clock (NTP-style, RTT/2). The request fires when the *server* reads 10:00:00 (`clock.py`). |
| Session expires / OTP at the worst moment | Login a few minutes early, keep-alive while waiting, automatic re-login that asks the human for the OTP. |
| "Money debited, no ticket" | Idempotency key per attempt. An ambiguous timeout triggers **reconciliation**, never a blind re-book (`executor.py`). |
| First choice sells out | Ranked fallback options (other trains, other classes; non-AC opens an hour later), tried in order automatically. |
| Getting WL when a confirmed berth was needed | `confirmed_berths_only` policy (IRCTC's "book only if confirmed berths are allotted"). |

## Architecture

```
            ┌──────────────────────────── before the window ───────────────────────────┐
 traveller ─┤  Claude agent (agent.py)  ── MCP ──►  tatkal-booking MCP server            │
     ▲      │   decides: which trains/classes,      tools: get_tatkal_window, search_trains,│
     │      │   ranking, fare cap, what to do       check_availability, propose_booking_plan│
     │      │   when something goes wrong           login, execute_booking_plan,           │
     │      │                                       get_booking_status, ask_human          │
     │      └───────────────────────────────────────────────┬─────────────────────────────┘
     │   MCP elicitation (human-in-the-loop)                │ approved plan only
     ├── approve plan + fare cap                            ▼
     ├── enter OTP (goes straight to the server, never to the LLM)
     └── decide anything outside approved bounds   BookingExecutor (executor.py), no LLM
                                                    clock sync → wait → fire → retry/jitter
                                                    → sold out? next option → payment fail?
                                                    retry → ambiguous? reconcile → result
                                                                │
                                                     BookingProvider (providers/)
                                                     MockProvider │ PartnerApiProvider
```

**Who decides what**

* **Agent (Claude)**: research, ranking alternatives, choosing a fare cap, reacting to
  `needs_human` results (ask the traveller, propose a revised plan).
* **Executor (code)**: anything time-critical. It never leaves the approved bounds.
* **Human**: approves the plan and the money, enters OTPs, and makes any call outside the bounds.
  These gates are enforced in the MCP server. `execute_booking_plan` refuses an unapproved plan,
  and if the client cannot show elicitation prompts, every gate fails closed.

**Data handling**

* IRCTC/partner credentials are read from environment variables (or your secret manager) inside the
  provider. They are never tool arguments, tool results or log entries.
* Passenger names and ages stay server-side (`profile.json`). The agent only sees the passenger count.
  The human sees full details in the approval prompt.
* Every decision is written to `runs/audit.jsonl`, without OTPs or credentials.

## Quick start

```bash
cd tatkal-agent
pip install -e ".[dev]"
cp profile.example.json profile.json        # edit passengers (max 4 per Tatkal PNR)

# 1) Fire drill: the executor against a hostile simulator (503 storm, sell-out,
#    payment declines, lost responses). No LLM or API key needed.
tatkal-agent drill

# 2) Full agent with human-in-the-loop (simulator opens the window 20 s after start).
export ANTHROPIC_API_KEY=...                 # from your shell or secret manager, never committed
tatkal-agent run "Tatkal for 2 people NDLS to MMCT on 2026-11-20, 3A preferred, SL is fine as backup"

# 3) Use the tools from Claude Code / Claude Desktop / any MCP host
tatkal-agent serve                          # MCP server on stdio
```

In the simulator the OTP is `123456`.

### Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `TATKAL_PROVIDER` | `mock` | `mock` or `partner` |
| `MOCK_WINDOW_OPENS_IN_SECONDS` | `20` | Simulator window offset, or `real` for the real 10:00/11:00 schedule |
| `TATKAL_PROFILE` | `profile.json` | Passenger profile path (falls back to the example) |
| `TATKAL_AGENT_MODEL` | `claude-opus-5-5` | Model used by the planning agent |
| `PARTNER_API_BASE_URL`, `PARTNER_API_KEY_ENV` | | Authorised partner integration (see `providers/partner.py`) |

The agent request enables the API's server-side refusal fallback (`fallbacks: "default"`). Remove
it in `agent.py` if you don't want it.

## Tests

```bash
python -m pytest -q
```

The tests cover the executor's failure handling (sell-out fallthrough, overload retries,
reconciliation without double-booking, fare-cap escalation, payment-decline escalation,
re-login on session expiry), the MCP server over the real protocol with scripted human responses
(approval, decline, wrong OTP, PII not exposed), and the agent loop wiring with a scripted model.

## Going to production

1. Implement `PartnerApiProvider` against your authorised partner API. Keep `book()` idempotent and
   implement `find_booking()` for reconciliation.
2. Run the MCP server over streamable HTTP behind auth if the human UI is a web or mobile app.
   Show elicitations as push notifications or in-app prompts so OTP and approval arrive in seconds.
3. Run the executor in a region close to the backend, and schedule `login` about 5 minutes before
   the window.
4. Monitor attempt latency and outcomes from `runs/audit.jsonl`.
5. Be honest with users: nobody can *guarantee* a confirmed Tatkal berth. This system maximises the
   chance (timing, fallbacks, no wasted retries) and never books outside what the user approved.
