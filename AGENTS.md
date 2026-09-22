# AGENTS.md

## Project intent

JevPip is a local market-research and paper-trading application using GMO market data.

Current research priority:
- Fifty+ is the primary direction-source experiment.
- Compare Jev Fifty+ against coin-flip random controls under the same market path, cost model, paper OCO semantics, spread gate, and reentry wait.
- Do not interpret a single backtest or a random-control result as evidence of profitability.
- Event/daytrade/scalp remain separate Jev experiments; do not mix their conclusions with the Fifty+ direction-source comparison.

## Safety boundary

- Paper trading only.
- GMO Private API is read-only GET for account/positions.
- Do not add order POST, cancel/replace, or other live-trading mutation paths unless a separate explicit design decision requires them.
- Keep model outputs bounded. Jev selects from code-owned candidates; it must not generate arbitrary orders, quantities, leverage, TP/SL, commands, or executable triggers.
- Do not weaken code-owned market freshness, spread, margin/capacity, max-DD, session/account-version, or response validation guards merely to increase fill frequency.

## Important semantics

- Fifty+ direction is mandatory UP/DOWN when its code-owned entry gate is ready.
- Fifty+ uses symmetric NET-PnL paper OCO boundaries fixed at entry.
- Fifty+ default post-close reentry wait is 600 seconds.
- Jev Fifty+ may receive observed official-event context when the UI toggle is enabled.
- Event mode is event-driven: code monitors price-cross/bar/timeout conditions between Jev calls; avoid heartbeat-style polling.
- Event/Fifty+ TypeSafe payloads are bounded: no raw tick tape, latest 16 bars per timeframe + current bar + indicators, and 10 recent executions. Broker-internal history remains fuller.
- Coin flip is a random control, not a zero-cost or guaranteed 50% realized-PnL baseline.

## Change discipline

Before changing behavior:
1. Read README.md.
2. Read docs/CURRENT_STATE.md.
3. Read docs/JEV_AUTOPILOT.md for Jev execution semantics.
4. Read docs/FIFTY_PLUS.md for Fifty+ semantics.
5. Read docs/BACKTEST_RESEARCH.md for experiment taxonomy.
6. Check DESIGN.md for historical design constraints and open GitHub issues for planned refactors.

Prefer small, reviewable changes that preserve accounting and causal/replay semantics.

Do not refactor broker/paper.py, broker/autopilot.py, Fifty+ execution/accounting, or observer live semantics merely because files are large. Issue #41 tracks staged UIController/service extraction.

Do not commit measured trading performance, private account data, API credentials, or local replay/output data to the public repository.

## Verification

For code changes, run at minimum:
- `uv run pytest`
- `node --test tests/web_ui.test.cjs`

When behavior changes, update the relevant docs and add regression coverage. If a live/API behavior cannot be verified in the available environment, state that explicitly rather than treating it as confirmed.
