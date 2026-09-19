# JevPip

JevPip is an experimental real-time FX decision system combining **TypeSafe AI's Jev** with the **GMO Coin Foreign Exchange FX API**.

The project starts in **observer/paper mode only**. It will collect USD/JPY market data, ask Jev narrow probabilistic questions, record outcomes, and evaluate whether any signal survives spread, fees, latency, and baselines before live trading is even considered.

## Start here

**Read [DESIGN.md](./DESIGN.md) before implementing anything.**

The design document contains:

- project origin and prior Jev experiments
- Jev / GMO FX API assumptions and official references
- proposed architecture and directory layout
- market-state and Jev-question design
- logging and evaluation metrics
- phased roadmap from observer → paper → optional tiny live
- security and risk requirements
- handoff instructions for the next development chat

## Current status

- Repository created
- Architecture/design documented
- No implementation yet
- Live trading must remain disabled by default
