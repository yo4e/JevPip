# JevPip

JevPip は、**GMOの市場データを使うローカル・マーケットターミナル兼研究アプリ**です。

現在は、対円FX 12ペアと BTC/JPY を対象に、

- historical / live chart
- raw tick収集
- code-based paper trading
- strategy backtest
- raw tick replay comparison
- optionalなJev研究レイヤー

を1つのローカルUIへまとめています。

> **実売買はしません。** GMO Private APIは、設定した場合も口座・建玉のGET参照だけです。注文POSTは実装していません。

Jevは必須ではありません。Jev OFFでも、チャート・データ収集・paper strategy・backtestは動きます。

## Quick start

Python 3.12 と [uv](https://docs.astral.sh/uv/) を用意します。

```bash
uv sync --extra dev
uv run jevpip ui
```

標準では次で起動します。

```text
http://127.0.0.1:8765
```

ブラウザを自動で開かない場合:

```bash
uv run jevpip ui --no-open
```

すでにclone済みなら:

```bash
git pull
uv sync --extra dev
uv run jevpip ui
```

終了は起動したターミナル / PowerShellで `Ctrl+C`。

## ブラウザUI

UIは日本語です。中央にチャート、右にpaper strategy設定、下に口座・戦略検証・ログを置いた1画面の市場研究UIです。

主な機能:

- 対円FX 12ペア / BTC/JPY の切替
- GMO Public APIのlive ticker
- historical KLine
- 1分 / 5分 / 15分 / 1時間チャート
- MA20 / MA200
- live MIDをhistorical chart末尾へ接続
- 仮想資金・建玉・PnL表示
- paper tradeのOPEN / CLOSE marker
- Jev ON / OFF
- read-onlyなGMO FX実口座表示
- 下部ターミナルの高さをドラッグで変更

UI上で変更した設定は、現時点では恒久保存しません。下部ターミナルの高さだけはブラウザのlocalStorageへ保存します。

## 対応銘柄

### 対円FX

現在paper PnLをJPYのまま扱える12ペアを有効にしています。

- USD/JPY
- EUR/JPY
- GBP/JPY
- AUD/JPY
- NZD/JPY
- CAD/JPY
- CHF/JPY
- TRY/JPY
- ZAR/JPY
- MXN/JPY
- HUF/JPY
- SEK/JPY

非対円FXは、historical cross-rateを含むJPY accountingを実装してから追加する方針です。

### BTC/JPY

BTCはGMOコイン暗号資産Public APIの現物ticker / KLineを使います。

PaperBrokerでは比較研究のためLONG / SHORT両方向を扱いますが、BTCのSHORTは**synthetic short**です。

## Paper trading

選べるstrategy:

- **Momentum**
- **RSI mean reversion**
- **MA trend**
- **Jev signal**（研究対照）

RSI / MAのlive paper入力は、

- tick
- 5秒bar
- 15秒bar
- 1分bar
- 5分bar

から選べます。bar modeは確定barのcloseだけで判断します。

PaperBrokerは次を反映します。

- BID / ASK
- configured slippage
- instrumentごとのreference fee
- TP / SL
- max holding
- cooldown
- single position

表示する主な指標:

- net / gross PnL
- fee / slippage cost
- Profit Factor
- max drawdown
- win rate
- average trade / win / loss
- exit reason別集計

> Paper tradingは将来利益を示すものではありません。板の深さ、部分約定、動的slippage、資金・証拠金制約などは完全にはモデル化していません。

## Safety supervisor

Jevとは独立したdeterministic supervisorがあります。

- market closed → `PAUSE_ALL`
- stale market data → `PAUSE_ALL`
- spread over limit → `PAUSE_ENTRY`
- spread near limit → `CAUTION`
- BLS公式scheduled event（local risk=high/critical）→ 前30分〜後15分 `PAUSE_ENTRY`
- BLS公式scheduled event（local risk=medium）→ 前10分〜後5分 `CAUTION`
- BOJ Summary of Opinions / MPM Minutes → 原則8:50 JSTの公式時刻を使い `CAUTION`
- Fed定例FOMC statement → 公式14:00 ETの公開時刻を使い `PAUSE_ENTRY`

BLS calendar、BOJ MPM release schedule、Fed FOMC calendarはObserver開始時とUIの「公式イベント更新」から取得します。
Observer稼働中は標準15分ごとに再取得し、各sourceの取得結果・失敗・その時点のevent metadataを `data/context/<source>/YYYY-MM-DD.jsonl` へrevision logとして保存します。raw本文は保存しません。
CPI / PPI / Employment Situation等のrisk分類はBLS公式の重要度ではなく、JevPip側の比較実験用local classificationです。

supervisorはリスクを**厳しくする方向にしか動けません**。

Jev supervisorも同じ境界へ接続済みです。Jev ON + code strategy + 安全監督ONでは、external contextを含むbounded questionsから `NORMAL / CAUTION / PAUSE_ENTRY` とallowlist済みstrategy候補を作り、paper entry gateへ反映します。Jevのadviceには15〜30秒のTTLがあり、期限切れで自動失効します。code側の `PAUSE_ENTRY / PAUSE_ALL` をJevが解除することはできません。

## 3つの検証機能

### 1. 戦略BT

historical 1分足をPaperBrokerへ時系列で流し、code-only strategyを実際にentry / exitさせます。

対応:

- Momentum
- RSI mean reversion
- MA trend

右側の現在設定から主に次を使います。

- size
- TP / SL
- max spread
- slippage
- Momentum threshold
- RSI params
- MA params
- instrument fee model

historical専用:

- Momentum参照本数
- 最大保有本数
- 再entry待機本数

結果:

- net PnL
- Profit Factor
- max drawdown
- trade count / win rate
- fee
- average trade
- exit reason
- No Trade baseline
- Buy & Hold baseline

FXはhistorical BID / ASK closeを使います。

BTC historical KLineにはBID / ASKがないため、`bid = ask = close` の近似でreference feeとconfigured slippageを反映します。

> 戦略BTは1分足の**close点だけ**でTP / SL等を評価します。1分の途中の値動き順序は復元しないため、tick-level execution backtestではありません。

### 2. 戦略比較

保存済みraw tickを、同じsize / cost modelで比較します。

標準比較:

- No Trade
- Buy & Hold
- Momentum
- RSI mean reversion
- MA trend

安全監督ON/OFFや、RSI / MAのtick / closed-bar入力を変えて再生できます。

CLI:

```bash
uv run jevpip compare \
  --instrument BTC \
  --file data/raw_ticks/BTC/2026-09-19.jsonl
```

1分barで比較する例:

```bash
uv run jevpip compare \
  --instrument BTC \
  --file data/raw_ticks/BTC/2026-09-19.jsonl \
  --bar-seconds 60
```

### 3. 統計リプレイ

historical 1分足をFeature pipelineへ流し、次の1分の値動きを集計する研究機能です。

**売買戦略のPnLバックテストではありません。**

FXではhistorical BID / ASKからspread-aware edgeも見ます。BTCはclose-to-closeの変化だけを扱います。

CLI:

```bash
uv run jevpip backtest --date 20260918 --profile technical
```

## Jevの現在地

Jevは現在、research componentです。

標準Feature preset:

- `minimal`
- `technical`
- `moon_only`
- `price_and_moon`
- `random_control`
- `kitchen_sink`

初期Jev questions:

- direction
- market_is_noisy
- reversal_risk
- trend_strength

Jev answerと、code側のsignal / safety ruleは分離しています。

将来はJevを直接の売買方向決定器よりも、**code strategyを監督するsupervisor**として使う方向を優先しています。

Jev supervisor用には固定schemaを実装済みです。

- `NORMAL`
- `CAUTION`
- `PAUSE_ENTRY`
- `PAUSE_ALL`
- allowlist済みstrategy
- confidence
- TTL
- reason

Jevは数量、TP / SL、レバレッジ、任意commandを指定できません。

external contextはBLS / BOJ / Fedのofficial scheduled eventへ接続済みです。Jev supervisorへ渡すcontextはdecision時点で既知のrevisionだけに限定し、future observationや後日訂正を過去へ逆流させません。

## Jevを使う場合

raw tick収集やcode-only strategyだけならTypeSafe API keyは不要です。

Jevを使う場合は、`.env.example` を参考にローカルの `.env` へ設定します。

```env
TYPESAFE_API_KEY=...
```

API keyはブラウザへ返しません。

## GMO実口座をread-onlyで表示する場合

オプションです。注文権限は不要です。

```env
GMO_FX_API_KEY=...
GMO_FX_API_SECRET=...
```

現在使うPrivate API:

```text
GET /private/v1/account/assets
GET /private/v1/openPositions?symbol=USD_JPY
```

Private clientはGET専用で、注文POST endpointを持ちません。

Private GETには共有rate limiterがあり、read-only GETは自動retryしません。

## Safety boundary

現時点で存在しないもの:

- GMO Private APIによる注文
- 実ポジションの作成・決済
- 自動実売買
- live trading

`LIVE_TRADING=true` を設定すると起動時に拒否します。

将来注文機能を検討する場合も、rate limit、idempotency、reconnect sync、position / loss limit等を先に設計する方針です。

## CLI

Feature preset一覧:

```bash
uv run jevpip features list
```

Signal Policy一覧:

```bash
uv run jevpip signals list
```

raw tick観測:

```bash
uv run jevpip observe --profile minimal
```

Jevあり:

```bash
uv run jevpip observe --profile minimal --with-jev
```

## Data

runtime dataは `data/` 以下へ保存し、Gitでは無視します。

```text
data/
├── raw_ticks/
│   └── <instrument>/
├── decisions/
│   └── <instrument>/
├── context/
│   └── <source>/
└── backtests/
```

TypeSafeのperformance / benchmarkに関する実測値は、契約上の公開範囲を確認したうえで扱い、Jevのaccuracy / Brier score / PnL等は公開repoへcommitしない方針です。

## Development

```bash
uv sync --extra dev
uv run pytest
```

unit testは外部APIへ依存しないものを基本とし、live connectivityはintegration checkとして分離します。

## Documents

- [CURRENT_STATE.md](./docs/CURRENT_STATE.md) : 現在できること、未実装、次の一手
- [DESIGN.md](./DESIGN.md) : 設計判断・実装履歴
- [RESEARCH_2026-09-19.md](./docs/RESEARCH_2026-09-19.md) : 実装開始前の類似実装調査
- [EXTERNAL_CONTEXT_RESEARCH_2026-09-19.md](./docs/EXTERNAL_CONTEXT_RESEARCH_2026-09-19.md) : Jev supervisor向け公式event source / provenance / look-ahead設計

## 現在の位置づけ

JevPipは現在、

1. **Market Terminal**
2. **Paper Broker**
3. **Observer / Feature Lab**
4. **Backtester**

を1つのローカルアプリへまとめた段階です。

次の大きなテーマは、**同じmarket path / cost modelで technical only・deterministic event supervisor・Jev supervisor・Jev direct signal を比較するexperiment harnessを作ること**です。
