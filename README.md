# JevPip

JevPip は、**GMOの市場データを使うローカル・マーケットターミナル兼研究アプリ**です。

現在は、対円FX 12ペアと BTC/JPY を対象に、

- historical / live chart
- raw tick収集
- code-based paper trading
- Jevおまかせ（コスト・口座状態を見た目標ポジション判断）
- strategy backtest
- raw tick replay comparison
- optionalなJev研究レイヤー

を1つのローカルUIへまとめています。

> **現時点では実売買しません。** まずpaper tradingで戦略・Jev・安全監督・cost modelを検証しています。安全機構と注文同期を整えたうえで、GMO Private APIによる実売買対応を予定しています。現在のPrivate API利用は口座・建玉のGET参照だけで、注文POSTはまだ実装していません。

Jevは必須ではありません。Jev OFFでも、チャート・データ収集・paper strategy・backtestは動きます。

UIの基本paper modeは **Jevおまかせ** です。現在は **デイトレ / スキャルピング / Fifty+** の3スタイルを選べます。デイトレは1分足中心で標準5分ごとに10分先を再評価し、スキャルピングは直近raw/live tickを中心に標準1秒ごとに30秒先を再評価します。Fifty+は常に1ポジションを持つ実験モードで、ポジション決済時だけJevへ次の `UP / DOWN` 二択を問い合わせ、同じ幅のネット利確・損切りへ進みます。FXはpips、BTCは円損益で勝負幅を指定できます。見通す時間は判断間隔と独立し、従来の固定TP/SL・8秒決済は適用しません。任意制約、手数料込みの損益内訳、約定履歴をlive paperとJev BTで共用します。おまかせOFFで従来モードに戻せます。仕様・制限・検証手順は [JEV_AUTOPILOT.md](./docs/JEV_AUTOPILOT.md) を参照してください。Fifty+の発想、実験仮説、1:1の考え方は [FIFTY_PLUS.md](./docs/FIFTY_PLUS.md) にまとめています。


## ライセンス・免責・サポート

JevPipは **MIT License** で公開しています。利用・改変・再配布はMIT Licenseの条件に従って自由に行えます。

JevPipは実験的な市場研究ソフトウェアです。**利益、収益性、動作、データの正確性、特定目的への適合性を保証しません。** 利用によって生じた取引損失・逸失利益・その他の損害について、作者は責任を負いません。実運用を含め、利用は各自の判断と責任で行ってください。

JevPipが役に立ったり、もしこれで利益が出たりしたら、開発者にコーヒーを1杯奢ってもらえるとうれしいです。☕

- [Ko-fiでコーヒーを奢る](https://ko-fi.com/yo4e)

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
- 右サイド下部の控えめなKo-fi支援リンク

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

## Decision trace

paper modeのlive tickごとに、A/B/C/D比較の土台となるdecision traceを `data/decision_traces/<instrument>/YYYY-MM-DD.jsonl` へ保存します。schema versionは明示し、現在は `1` です。

1行には最低限、次を残します。

- run config
- cost model version
- gate適用前のcode candidate
- Jev directionとdecision timing
- Jev direction gate適用後のentry candidate
- deterministic / official event / Jev supervisor / combined gate
- blocked-entry reason
- Jev direct position-management decision
- final action
- holding time / turnover
- paper trade linkage

supervisorにentryを止められたtickでも元のcode candidateを残します。これにより、次のexperiment harnessでblocked candidateのcounterfactualを同じmarket path / cost model上で評価できます。

## 5つの検証機能

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

### 4. A/B/C/D experiment

Jev + code strategy + 安全監督をすべてONにしたsource run（C-run）のdecision traceを、Jevへ再問い合わせせず再生します。

```bash
uv run jevpip experiment \
  --trace data/decision_traces/USD_JPY/2026-09-20.jsonl
```

1ファイルに複数runがある場合:

```bash
uv run jevpip experiment \
  --trace data/decision_traces/USD_JPY/2026-09-20.jsonl \
  --run-id <run_id>
```

比較するvariant:

- **A**: technical only
- **B**: technical + deterministic supervisor
- **C**: technical + deterministic + Jev supervisor
- **D**: Jev direct direction control

同じmarket pathと同じpaper cost modelを使い、net PnL / PF / max drawdown / trade count / fee / turnover / pause duration等を比較します。

B / Cについては、supervisorやJev direction gateに止められたcode candidateを、同じ後続market pathで1-positionだけ仮想実行します。これにより、

- avoided loss
- missed profit
- false pause count

を集計します。連続した同一blockは1 episodeとして扱い、仮想tradeが重なるcandidateは二重計上しません。

Dはsource C-runで記録済みのJev directionだけを再利用します。source runではcounterfactualなD position向け `position_action` を因果的に取得できないため、DのexitはTP / SL / max hold等のcode-owned exitだけで比較します。

`--json` でmachine-readableな結果を出せます。Jev performanceの実測結果はpublic repoへcommitしません。


### 5. Jev historical replay

通常の1分足バックテストとは分離して、**保存済みraw tickに現在のJevを再実行する研究リプレイ**をUIの「Jev BT」タブから実行できます。

- sourceは `data/raw_ticks/<instrument>/YYYY-MM-DD.jsonl`
- historical 1min KLineは使わない
- 検証時間: 30秒 / 1分 / 5分 / 15分 / 1時間 / 6時間 / 1日
- Jev判断間隔: 1 / 2 / 5 / 10 / 30 / 60秒
- API実latencyをhistorical market timeへ反映
- Jev応答待ち中は次のcallを開始しない
- Jev direct paper entry / bounded HOLD-CLOSE / code-owned TP・SL・max holdを使う

実行前に**最大Jev call数**をraw tickから計算します。TypeSafeが過去のcallで `usage.input_tokens` / `usage.output_tokens` を返していれば、直近最大100件の平均からtoken消費目安も表示します。usage実績がない場合は数字を捏造せず「推定不能」と表示します。\n\n2026-09-20時点のTypeSafe公開価格では、**input tokenのみ課金対象で $0.042 / 1M tokens、output tokenは無料**です。そのためJev BTでは、事前見積り・実行結果ともに `input（課金対象）` / `output（無料）` / `reported total` を分け、input usageから概算API costも表示します。JevPipの表示はAPI responseのusageと公開価格からの計算であり、TypeSafe console側の請求・Usage表示そのものを確認した値ではありません。

実行ボタンでは、

> ⚠ Jev APIを使用します。TypeSafeのトークンを消費します。

という確認を必須にしています。API側でもacknowledgementがないrunは拒否します。

1runのハード上限は **10,000 Jev calls** です。たとえばraw tickが十分ある場合、1時間 × 1秒は最大約3,600 callsで実行範囲ですが、1日 × 1秒は約86,400 callsになるため拒否されます。期間を短くするか判断間隔を広げます。

> これは**現在のJevモデル**へ過去時点までのmarket stateを渡すhistorical replayです。当時存在したモデルを再現するものではありません。また初版ではofficial event contextをhistorical replayへ注入しません。

runtime結果は `data/jev_replays/<instrument>/` へ保存し、Gitでは無視します。performance実測値をpublic repoへcommitしない方針は他のJev実験と同じです。

## 従来のJev方向判定・supervisor（おまかせOFF）

従来モードは比較用のresearch componentとして引き続き利用できます。以下はおまかせOFFの仕様です。

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
- position_action（Jev directでpaper position保有中のみ、HOLD / CLOSE）

Jev answerとcode側のstrategy / safety ruleは分離しつつ、paper modeで **Jev判断を追加** をONにした場合はJevをdirection gateとして新規entryへ反映します。

- code strategyがLONG候補 + Jev direction LONG → entry候補を通す
- code strategyがSHORT候補 + Jev direction SHORT → entry候補を通す
- Jev direction WAIT / 反対方向 / stale / warmup → 新規entryしない
- noise / reversal / trend は research filter と supervisor 用に残し、direction gateそのものは止めない
- 既存positionのTP / SL / max hold決済はJev WAITで止めない

Jev direct signal strategyは引き続きresearch controlとして別系統です。Jev directでpositionを持っている間は、方向予測とは別のboundedな `HOLD / CLOSE` 判断を使います。

- 反対方向のdirection予測だけではpositionを閉じない
- `CLOSE` はcode-owned thresholdを満たした強い回答だけ採用
- 標準では別々のJev decisionで2回連続 `CLOSE` を確認
- `HOLD` が入るとCLOSE confirmationをreset
- 標準2秒のminimum holdを越えるまでJev CLOSEを適用しない
- position actionにも鮮度制限を掛け、古い回答は無視
- 判断は、そのJev callが参照した同じpositionの `opened_at` と一致するときだけ有効
- TP / SL / `max_hold_seconds` は引き続きcode-ownedで先に評価する

`max_hold_seconds` はJev directでもposition horizonとして働き、Jevが延長することはできません。

Jevには選択Featureに加え、look-ahead-safeなofficial event contextと、最小限のpaper state（configured strategy、直近strategy判断、position side / age）を渡します。API key、secret、口座credentialsは渡しません。

Jev supervisorも併用できます。

paper modeの意思決定レイヤーは独立にON/OFFできます。

- コード戦略 ON / Jev OFF: code-only
- コード戦略 ON / Jev ON: code strategy + Jev direction一致gate
- コード戦略 OFF / Jev ON: Jev direction単独
- コード戦略 OFF / Jev OFF: 新規entryなし
- 安全監督は上記と独立してON/OFF

安全監督OFFではmarket status / stale / spread / official eventのentry vetoを適用しません。既存positionのTP / SL / max hold等の決済ロジックは維持します。

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

Jevを使う場合は、右上の **⚙ 設定** からTypeSafe API keyを保存できます。保存先はローカルの `.env` で、保存済みのkey値そのものはブラウザへ返しません。

手動設定も引き続き使えます。

```env
TYPESAFE_API_KEY=...
```

TypeSafe APIが返す `usage.input_tokens` / `usage.output_tokens` は、現在の観測セッションについてUIでcall数・input・output・totalを集計表示します。usageが返らないcallは推定せず、報告済みcall数を分けて扱います。

## GMO実口座をread-onlyで表示する場合

オプションです。注文権限は不要です。右上の **⚙ 設定** からAPI key / secretを保存できます。

手動設定も可能です。

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
├── decision_traces/
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
- [JEV_AUTOPILOT.md](./docs/JEV_AUTOPILOT.md) : Jevおまかせの契約・会計・制約・replay
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

Jevおまかせのpaper prototypeと、従来モードのA/B/C/D experiment harnessを実装済みです。次は期間を分けたraw tick replayで、手数料と売買頻度を含めて比較する段階です。収益性は未検証です。
