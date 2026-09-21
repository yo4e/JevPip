# JevPip

JevPip は、**GMOの市場データを使うローカル・マーケットターミナル兼研究アプリ**です。

現在は、対円FX 12ペアと BTC/JPY を対象に、

- historical / live chart
- raw tick収集
- code-based paper trading
- 排他的な3つのpaper判断モード（Jev / 戦略 / スピリチュアル実験）
- strategy backtest
- spiritual Fifty+ backtest
- raw tick replay comparison
- optionalなJev研究レイヤー

を1つのローカルUIへまとめています。

> **現時点では実売買しません。** 現行スコープはpaper tradingとread-onlyな実口座参照です。GMO Private APIは口座・建玉のGET参照だけを使い、注文POST経路は実装していません。将来live tradingを検討する場合も、別途安全設計と明示的な実装判断を先に行います。

paper取引の判断系は、UI上で **Jevモード / 戦略モード / スピリチュアルモード** の3つに分離しています。同時には動きません。

- **Jevモード**: Jev APIだけが売買判断を担当。デイトレ / スキャルピング / Fifty+を選ぶ
- **戦略モード**: Jev APIを呼ばず、Momentum / RSI逆張り / MAトレンドのコード戦略を使う
- **スピリチュアルモード**: Jev APIと通常戦略を使わず、Fifty+の売買骨格に月相・太陽星座・ランダムタロット・コイントスの方向ルールを接続する実験用baseline

Jevモードのデイトレは標準15分ごと、スキャルピングは標準60秒ごとに、固定の予測時間を課さず現在の最適total positionを再判断します。どちらもFifty+と同じ `trader_context_v1` を使い、1分 / 5分 / 15分 / 1時間足、基本テクニカル、口座/PnL、cost、recent execution等を広くJevへ渡します。短い判断間隔ほどJev API callとinput token消費が増えます。Fifty+は1ポジションずつ持ち、決済後は標準60秒待って次の方向を決めます。FXはpips、BTCは円損益で対称の勝負幅を指定できます。仕様・制限は [JEV_AUTOPILOT.md](./docs/JEV_AUTOPILOT.md)、Fifty+の発想と実験ルールは [FIFTY_PLUS.md](./docs/FIFTY_PLUS.md) を参照してください。


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

UIは日本語です。中央にチャート、右に3つの排他的な判断モードを持つセッション設定、下に現在状態・検証・ログを置いた1画面の市場研究UIです。

主な機能:

- 対円FX 12ペア / BTC/JPY の切替
- GMO Public APIのlive ticker
- 停止中もPublic RESTで価格 / spreadを5秒程度ごとにプレビュー（保存・売買判断には不使用）
- historical KLine
- 1分 / 5分 / 15分 / 1時間チャート
- MA20 / MA200
- live MIDをhistorical chart末尾へ接続
- 仮想資金・建玉・PnL表示
- paper tradeのOPEN / CLOSE marker
- Jev / 戦略 / スピリチュアルのpaper判断モード切替
- read-onlyなGMO FX実口座表示（右上の ⚙ 設定内）
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

paper取引では、判断方式を3つの排他的なモードから選びます。

### Jevモード

Jev APIが売買判断を担当し、コード戦略や旧research filterを売買判断へ混ぜません。

- **デイトレ**: `trader_context_v1` を利用、標準15分ごとに現在の最適total positionを再判断
- **スキャルピング**: `trader_context_v1` を利用、標準60秒ごとに現在の最適total positionを再判断。短くするほどtoken消費が増える
- **Fifty+**: 1ポジションずつ。決済後は標準60秒待ち、設定した対称NET勝負幅を実数で示してJevが `UP / DOWN` を二択で判断。5 pips設定なら「+5 pips / -5 pips のどちらへ先に到達するか」を予測する

### 戦略モード

Jev APIを呼ばず、コードだけでpaper売買します。通常UIのおすすめプリセットは Momentum / RSI mean reversion / MA trend です。

### スピリチュアルモード

Fifty+のentry / exit骨格、安全弁、会計をそのまま使い、次の方向だけを実験用の方向源へ差し替えます。

- **月相**: 朔望月の前半をLONG、後半をSHORTとする単純な二択baseline
- **太陽星座の極性**: 固定カレンダーの12星座を陽/陰へ分け、LONG / SHORTへ対応させるbaseline
- **タロット1枚引き**: ラウンドごとに大アルカナをランダムに1枚引き、正位置をLONG、逆位置をSHORTへ対応させるジョーク寄りbaseline
- **コイントス**: ラウンドごとに完全ランダムで表/裏を引き、表をLONG、裏をSHORTへ対応させるrandom control

これは予測力や収益性を前提とするものではありません。月相・星座は決定論的、タロットとコイントスは実行ごとにランダムです。コイントスはJev Fifty+や他の方向源に優位性があるかを見るための基準群として使います。

Jev Fifty+とスピリチュアルモードは、数量やTP/SLの自由判断を方向源へ任せません。コード側が対称のネット損益境界、決済後待機、spread上限、往復コストgate、最大DD、fee / slippage、口座会計を管理します。詳細は [FIFTY_PLUS.md](./docs/FIFTY_PLUS.md) を参照してください。

PaperBroker / AutopilotBrokerは主に次を反映します。

- BID / ASK
- configured slippage
- instrumentごとのreference fee
- code-owned risk / exit rules
- FX paperの最大25xレバレッジによる必要証拠金近似（BTCは1x固定）
- Jev / スピリチュアルFifty+の最大DD 20%初期停止
- single position
- net / gross PnL、fee / slippage cost、Profit Factor、max drawdown、win rate

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

## 検証機能

検証系は、実装順ではなく目的で3分類します。

- **Performance backtests**: 戦略BT / スピBT / Jev BT。paper accountingでPnLを評価する
- **Comparison experiments**: 戦略比較 / A/B/C/D。同じmarket path上で判断源や介入条件を比較する
- **Statistical replay**: 統計リプレイ。売買PnLではなくfeatureと次の値動きを集計する

今後の追加機能も、まずこの3分類と「data source / decision source / execution policy」の組み合わせで表現できないか確認します。詳細と、Jev Fifty+ vs random controlをどこへ置くかは [BACKTEST_RESEARCH.md](./docs/BACKTEST_RESEARCH.md) を参照してください。

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

### 2. スピBT 🌙

UIの「スピBT」タブから、**月相Fifty+ / 太陽星座Fifty+ / タロットFifty+ / コイントスFifty+** をhistorical 1分足で再生します。戦略BTとは別機能です。タロットとコイントスは毎回ランダムなので、同じ条件でも結果が変わります。

Jev APIは使いません。liveのスピリチュアルモードと同じFifty+エンジンを使い、次を共用します。

- 月相 / 太陽星座の二択方向ルール
- 対称のネット損益勝負幅
- 決済後の再判断待機
- 最大spread
- 往復コストgate
- 最大DD停止
- FX paper leverage
- fee / slippage / paper accounting

結果にはnet PnL、PF、max DD、勝率、決済数、fee、LONG / SHORT entry数、No Trade / Buy & Hold baseline、約定履歴を表示します。

FXはhistorical BID / ASK closeを使います。BTCはhistorical KLineにBID / ASKがないため、`bid = ask = close` の近似でfee / slippageを反映します。

> スピBTも1分足の**close点だけ**でFifty+のTP / SLを評価します。1分の途中でどちらの境界へ先に触れたかは復元できないため、tick-level replayではありません。

### 3. 戦略比較

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

### 4. 統計リプレイ

historical 1分足をFeature pipelineへ流し、次の1分の値動きを集計する研究機能です。

**売買戦略のPnLバックテストではありません。**

FXではhistorical BID / ASKからspread-aware edgeも見ます。BTCはclose-to-closeの変化だけを扱います。

CLI:

```bash
uv run jevpip backtest --date 20260918 --profile technical
```

### 5. A/B/C/D experiment

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


### 6. Jev historical replay

現在のJevを過去データへ再実行する研究リプレイをUIの「Jev BT」タブから実行できます。日付は任意に選べます。

データ源は次の優先順です。

1. `data/raw_ticks/<instrument>/YYYY-MM-DD.jsonl` があれば保存済みraw tickを使う
2. raw tickがなければGMO Public APIのhistorical 1分足へ自動fallbackする

raw tick時は秒以下の市場経路を使えます。1分足fallback時はFXならhistorical BID / ASK close、BTCなら `bid = ask = close` 近似を使います。この場合、1分内の値動き順序、細かいspread変化、秒単位のentry timingは再現できません。結果欄へ使用データ源と誤差を明記します。

- 検証時間: 30秒 / 1分 / 5分 / 15分 / 1時間 / 6時間 / 1日
- Jev判断間隔: 1 / 2 / 5 / 10 / 30 / 60 / 300 / 900秒
- API実latencyをhistorical market timeへ反映
- Jev応答待ち中は次のcallを開始しない
- Jevモードのデイトレ / スキャ / Fifty+設定をpaper replayへ流用

実行前に**最大Jev call数**を実際に選ばれたデータ源から計算します。TypeSafeが過去のcallで `usage.input_tokens` / `usage.output_tokens` を返していれば、直近最大100件の平均からtoken消費目安も表示します。usage実績がない場合は数字を捏造せず「推定不能」と表示します。

2026-09-20時点のTypeSafe公開価格では、**input tokenのみ課金対象で $0.042 / 1M tokens、output tokenは無料**です。そのためJev BTでは、事前見積り・実行結果ともに `input（課金対象）` / `output（無料）` / `reported total` を分け、input usageから概算API costも表示します。JevPipの表示はAPI responseのusageと公開価格からの計算であり、TypeSafe console側の請求・Usage表示そのものを確認した値ではありません。

実行ボタンでは、

> ⚠ Jev APIを使用します。TypeSafeのトークンを消費します。

という確認を必須にしています。API側でもacknowledgementがないrunは拒否します。

1runのハード上限は **10,000 Jev calls** です。たとえばraw tickが十分ある場合、1時間 × 1秒は最大約3,600 callsで実行範囲ですが、1日 × 1秒は約86,400 callsになるため拒否されます。期間を短くするか判断間隔を広げます。

> これは**現在のJevモデル**へ過去時点までのmarket stateを渡すhistorical replayです。当時存在したモデルを再現するものではありません。また初版ではofficial event contextをhistorical replayへ注入しません。

runtime結果は `data/jev_replays/<instrument>/` へ保存し、Gitでは無視します。performance実測値をpublic repoへcommitしない方針は他のJev実験と同じです。

## 比較研究用の互換機能

Jevおまかせ以前の code strategy / Jev direction gate / Jev supervisor / A/B/C/D experiment は、**比較・研究用として内部互換を維持**しています。

通常UIでは独立した「研究・従来設定」は置かず、戦略モードの **「戦略の詳細設定・研究」** の中へ集約しています。Jevモードとスピリチュアルモードでは表示しません。Momentum / RSI / MAの実運用設定を先に置き、旧Feature / Signal Policy / Jev supervisorなどはさらに「比較研究用の旧設定」へ畳んでいます。

古い `strategy="jev"` 設定も互換入口として内部では受け付けますが、新しいUIでは独立strategyとして表示しません。詳細な契約・閾値・position managementは [CURRENT_STATE.md](./docs/CURRENT_STATE.md) と [DESIGN.md](./DESIGN.md) を参照してください。

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

runtime dataは `data/` 以下へ保存し、**`data/.gitkeep` 以外はGitで追跡しません**。

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
├── backtests/
└── jev_replays/
    └── <instrument>/
```

raw tick、paper約定、Jev応答、replay結果などはruntime artifactです。公開repoへサンプル実測データを残さず、必要な比較はローカルデータで行います。

TypeSafeのperformance / benchmarkに関する実測値は、契約上の公開範囲を確認したうえで扱い、Jevのaccuracy / Brier score / PnL等は公開repoへcommitしない方針です。

## Development

```bash
uv sync --extra dev
uv run pytest
node --test tests/web_ui.test.cjs
```

UIのJavaScript回帰テストはNode.js 18以降の組み込みtest runnerを使います（追加パッケージ不要）。

unit testは外部APIへ依存しないものを基本とし、live connectivityはintegration checkとして分離します。

## Documents

- [CURRENT_STATE.md](./docs/CURRENT_STATE.md) : 現在できること、未実装、次の一手
- [JEV_AUTOPILOT.md](./docs/JEV_AUTOPILOT.md) : Jevおまかせの契約・会計・制約・replay
- [FIFTY_PLUS.md](./docs/FIFTY_PLUS.md) : Fifty+の仮説・1:1境界・検証観点
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

Jevおまかせのpaper prototype、Fifty+、従来モードのA/B/C/D experiment harnessまで実装済みです。次はFifty+を含むpaper結果を十分な試行数・別期間・baselineと比較し、勝率だけでなくnet PnL、コスト、ラウンド数、時間帯・銘柄偏りを確認する段階です。収益性は未検証です。
