# JevPip Current State

更新日: 2026-09-19

この文書は、JevPipの**現在の実装状態と次の作業境界**を短く把握するためのhandoffです。

詳細な設計判断・経緯は [../DESIGN.md](../DESIGN.md) を参照してください。

## 現在の役割

JevPipはローカルで動くmarket research terminalです。

現在の4本柱:

1. Market Terminal
2. Paper Broker
3. Observer / Feature Lab
4. Backtester

Jevはoptionalなresearch / supervisor componentです。

## 対応市場

### 対円FX

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

JPY quoteのため、現在のpaper accountingでそのまま扱えます。

### BTC/JPY

- GMO暗号資産Public ticker
- historical KLine
- paper LONG / synthetic SHORT
- reference fee model

## Live market / chart

実装済み:

- Public WebSocket ticker
- historical chart backfill
- 1min / 5min / 15min / 1hour
- MA20 / MA200
- 約180 candleを目安に時間足ごとにvisible rangeを変更
- weekend / holiday fallback
- sparse / failed dataでchartが白紙になりにくいguard
- live MIDをhistorical chartへ接続

## Paper strategies

実装済み:

- Momentum
- RSI mean reversion
- MA trend
- Jev direct signal（research control）

RSI / MA input:

- tick
- 5s closed bar
- 15s closed bar
- 1min closed bar
- 5min closed bar

PaperBroker:

- real BID / ASK
- configurable adverse slippage
- instrument reference fee
- TP / SL
- max holding
- cooldown
- single position
- net / gross PnL
- PF
- max DD
- win rate
- average trade / win / loss
- exit reason aggregate

## Deterministic supervisor

state:

- NORMAL
- CAUTION
- PAUSE_ENTRY
- PAUSE_ALL

現在のguard:

- market closed
- stale market timestamp
- silent feed heartbeat
- spread over limit
- spread near limit

code supervisorはriskを緩和しません。

## Jev supervisor foundation

実装済み:

- fixed schema validator
- allowlisted strategy
- confidence
- TTL
- reason
- deterministic supervisorとのsafe merge

Jevはcode側の `PAUSE_ENTRY / PAUSE_ALL` を解除できません。

external context foundationも実装済み:

- provenance-first context item schema
- source / source_id / observed_at / scheduled_at / published_at
- currency / instrument tags
- decision時点のlook-ahead防止
- calendar revisionを過去へ逆流させないselection
- boundedなJev context state変換
- source / reuse調査: `docs/EXTERNAL_CONTEXT_RESEARCH_2026-09-19.md`

Jev schemaには含めない:

- arbitrary BUY / SELL order
- quantity
- TP / SL
- leverage
- arbitrary command / code

実装済み:

- BLS公式ICS adapter / runtime fetch
- BOJ MPM release schedule adapter
- Summary of Opinions / MPM Minutesの公式8:50 JST時刻
- BOJ source_idの日付はUTC変換後ではなく公式JST日付で固定
- Fed FOMC statement adapter（定例会合最終日14:00 ET）
- BLS / BOJ / Fedを独立・並列refresh
- 片方のsource取得失敗時も、他sourceとlast known-good dataを維持
- observer開始時のcontext refresh
- Observer稼働中の定期refresh（default 15分 / minimum 60秒）
- source別runtime revision log: `data/context/<source>/YYYY-MM-DD.jsonl`
- success / error / observed_at / bounded event metadataを保存
- raw calendar / article bodyはrevision logへ保存しない
- UIからの手動context refresh
- deterministic event-window supervisor
- high/critical: 前30分〜後15分 PAUSE_ENTRY
- medium: 前10分〜後5分 CAUTION
- paper新規entry gateへの接続
- UI上のevent supervisor / 次イベント表示
- Jev supervisor bounded questions
- technical state + external contextを同じJev callへ投入
- bounded adviceをpaper-onlyへ接続
- `NORMAL / CAUTION / PAUSE_ENTRY`
- allowlist済みstrategy override
- 15〜30秒TTLと自動失効
- deterministic event supervisorとのstrict merge
- UIでJev supervisor state / strategy / confidence / expiryを表示
- Jev ON + code strategyではJev direction gateをpaper新規entryへ適用
- code LONG/SHORTとfreshなJev direction LONG/SHORTが同方向のときだけentry候補を通す
- Jev direction WAIT / 反対方向 / stale / warmupでは新規entryを止める
- direction gateはdirection probability / marginだけで判定し、noise / reversal / trend はresearch filter・supervisor側へ分離
- existing positionのTP / SL / max hold exitはdirection gateで止めない
- Jev stateへconfigured strategy / latest strategy decision / position side・ageを追加
- external contextはJev ON時にdirection判断側へも渡す
- UIでWAIT gate理由と「Jev方向一致必須」を表示

未実装:

- BOJ policy decision本体（固定公開時刻がないため未接続）
- official post-release context
- A/B/C/D experiment harness / counterfactual metrics

## 3つの検証機能

### Strategy BT

historical 1min pointsをPaperBrokerへ流す。

対応:

- Momentum
- RSI
- MA

比較:

- strategy
- No Trade
- Buy & Hold

制約:

- 1min close-only execution
- intrabar high / low orderは復元しない
- BTCはhistorical BID / ASKがないため `bid = ask = close`
- Jev direct historical BTは未対応

### Raw tick strategy comparison

保存済みraw tickを同条件で再生。

比較:

- No Trade
- Buy & Hold
- Momentum
- RSI
- MA

deterministic supervisor ON/OFFとbar inputを切替可能。

### Statistical replay

historical 1min dataをFeature pipelineへ流し、次の1分のmove / edgeを調べる。

strategy PnL backtestではない。

## Private API / account

実装済み:

- FX account assets GET
- USD/JPY open positions GET
- read-only UI
- shared GET rate limiter
- 3秒cache

未実装:

- order POST
- order cancel / replace
- live position mutation
- live trading

`LIVE_TRADING=true` は起動時に拒否。

## Known limitations

- BTC historical backtestにhistorical spreadはない
- strategy BTは1min close-only
- raw tickは収集した日だけ高解像度replay可能
- paper modelはdepth / partial fill / dynamic slippage / margin constraintsを完全再現しない
- real account open position表示は現在USD/JPY中心
- non-JPY FX accounting未実装
- UI custom strategy parametersは恒久保存しない
- 複合entry / exit rule builder未実装

## Open design/work items

### Issue #3

GMO FX scalp operation constraints.

paper / read-only段階で実装済み:

- cooldown
- spread / fee / slippage
- stale feed
- market status gate
- Private GET rate limiter

live order導入まで保留:

- POST limiter
- idempotency
- reconnect order/account synchronization
- POST retry policy

### Issue #4

Technical strategy engine + Jev supervisor.

実装済み:

- strategy abstraction
- Momentum / RSI / MA
- deterministic supervisor
- Jev supervisor bounded schema
- raw tick comparison
- historical strategy BT

実装済み:

- external context source / reuse research
- provenance-first context schema
- look-ahead-safe context selection

実装済み:

- BLS official calendar adapter
- deterministic event-window supervisor
- paper entry gate / UI integration

未実装:

- BOJ policy decision本体の安全な時刻表現
- A/B/C/D experiment harness / counterfactual metrics

### Issue #5

Non-JPY FX pairs with historical cross-rate JPY accounting.

未着手。

## 次の大きなテーマ

Jevを「相場方向を直接当てる主体」よりも、**code strategyが負けやすい局面を避けるsupervisor**として検証する。

次の順序を推奨:

1. A/B/C/D experiment harnessを実装
2. A: technical only
3. B: technical + deterministic event supervisor
4. C: technical + deterministic + Jev supervisor
5. D: Jev direct signal control（research control）
6. blocked candidate entryのcounterfactualを同一market path / cost modelで計算
7. BOJ policy decision本体は固定時刻を捏造しない表現が決まってから追加

主に見る指標:

- net PnL
- Profit Factor
- max DD
- average loss
- fee / trade count
- Jevが止めたtradeのcounterfactual result
- avoided loss
- missed profit

目的は「Jevが未来を当てたか」だけではなく、**事故回避・regime selectionに価値があるか**を測ること。

## 新しいチャットへ引き継ぐ場合

最初に読むもの:

1. README.md
2. docs/CURRENT_STATE.md
3. DESIGN.md の Section 26, 29
4. GitHub Issue #4

次の作業テーマ:

> A/B/C/D experiment harnessとblocked-entry counterfactual metricsを実装する。
