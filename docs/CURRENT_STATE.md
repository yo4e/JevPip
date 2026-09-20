# JevPip Current State

更新日: 2026-09-20

この文書は、JevPipの**現在の実装状態と次の作業境界**を短く把握するためのhandoffです。

詳細な設計判断・経緯は [../DESIGN.md](../DESIGN.md) を参照してください。

## 現在の役割

JevPipはローカルで動くmarket research terminalです。

現在の4本柱:

1. Market Terminal
2. Paper Broker
3. Observer / Feature Lab
4. Backtester

UIの基本paper modeはJevおまかせです。Jev OFFのコード戦略、従来の方向判定・supervisorも比較用に残しています。

## UI情報設計（Issue #21）

UIは機能を削らず、Jevおまかせ中心へ整理しています。

- 右サイドのprimary workflowは「銘柄 / 取引モード / Jev API / Jevおまかせ / 基準数量 / 仮想残高」を中心にする
- 実行中は `raw tick収集中 / Jev API ON|OFF / 銘柄` を常時表示し、Jev OFFでもデータ収集されることを明示する
- paper口座、建玉、最新Jev判断、約定履歴、損益内訳は下部の「現在」へ集約する
- Feature / Signal Policy / code strategy / supervisorなどは「研究・従来設定」へ残し、通常は閉じる
- Strategy BT / Jev BT / 戦略比較 / 統計リプレイには、使用データ・Jev API利用有無・token消費・目的を明示する
- 既存element IDとAPI contractは維持し、情報階層の変更を中心とする


## Jevおまかせ（Issue #17）

実装済みのpaper prototype:

- 基準数量の0.5/1/2倍とKEEP/FLATから目標総数量を選び、差分だけ約定
- 増額・部分決済・全決済・反転、加重平均建値と費用配賦
- 口座/equity・コスト・直近約定・確定足を同じJev stateへ投入
- 標準1秒判断と独立した見通し時間、従来の8秒強制exitを不適用
- 全任意制約のcheckbox、必須の鮮度・資金・session/version検証
- liveとhistorical raw replayで同一policy、historicalファンダONは拒否
- 約定表、損益分解、保有額・turnover・目標変更頻度・tick間隔
- 同時開始/重複API call抑止、停止時のworker終了待ち

詳細は [JEV_AUTOPILOT.md](JEV_AUTOPILOT.md)。有料APIでの収益性検証は未実施。以下のコード戦略・direction/supervisor・A/B/C/Dの説明は従来モードを指します。

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
- UIでWAIT gate理由とJev方向一致条件を表示
- paper modeは「コード戦略 / 安全監督 / Jev」を独立ON/OFF可能
- コード戦略OFF + Jev ONではJev direction単独でpaper entry
- コード戦略OFF + Jev OFFでは新規entryなし
- 安全監督OFFではmarket status / stale / spread / official eventのentry vetoを無効化
- Jev directのposition managementをdirection predictionから分離
- open position中だけbounded `HOLD / CLOSE` questionを追加
- 反対directionだけではcloseしない
- code-owned CLOSE probability / margin threshold
- 標準2回のdistinct CLOSE confirmation
- HOLDでconfirmation reset
- 標準2秒minimum hold
- stale / future position action拒否
- decisionが参照した `opened_at` と現在positionが一致するときだけ適用
- TP / SL / max holdは引き続きcode-ownedで優先
- paper live tickごとのdecision trace schema v1
- `data/decision_traces/<instrument>/YYYY-MM-DD.jsonl` へ永続化
- run config / cost model version
- gate前code candidate / Jev direction / gate後entry candidate
- deterministic / event / Jev supervisor / combined gate
- blocked-entry reason
- Jev position-management decision
- final action / holding time / turnover / paper trade linkage
- supervisorで止めたtickでもcode candidateを保持

実装済み:

- A/B/C/D experiment harness
- full C-run traceをJev再問い合わせなしでA/B/C/Dへ再生
- 同一market path / `paper-v1` cost model
- B/C blocked candidate episode抽出
- non-overlapping 1-position counterfactual
- avoided loss / missed profit / false pause count
- pause duration / turnover / strategy switch count
- Dはrecorded Jev direction + code-owned exitsで比較

未実装:

- BOJ policy decision本体（固定公開時刻がないため未接続）
- official post-release context
- 実採取traceでのexperiment validation / metric interpretation\n- Jev historical replayへのlook-ahead-safe official event context

## 検証機能

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

## Jev historical replay

実装済み:

- 保存済みraw tick専用のJev historical replay
- current Jev modelを過去時点までのstateで再実行
- 30秒〜1日の検証window
- 1 / 2 / 5 / 10 / 30 / 60秒 cadence
- API実latencyをhistorical market timeへ反映
- pending decision中の重複call抑止
- Jev direct paper entry + bounded HOLD/CLOSE
- preview時の最大call数計算
- recent reported usageからtoken消費目安
- usage実績なしでは推定不能
- UI + APIの二重token-use acknowledgement
- 1run 10,000 calls hard cap
- runtime output: `data/jev_replays/<instrument>/`

制約:

- historical 1min KLineはJev replayに使わない
- current modelによるreplayで、historical model再現ではない
- 初版はofficial event contextを注入しない
- 1日 × 1秒のような10,000 calls超過設定は拒否

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
- decision trace schema v1 / runtime JSONL persistence

実装済み:

- A/B/C/D experiment harness
- blocked-entry counterfactual metrics

未実装:

- BOJ policy decision本体の安全な時刻表現
- 実採取C-run traceでのexperiment validation

### Issue #5

Non-JPY FX pairs with historical cross-rate JPY accounting.

未着手。

## 次の大きなテーマ

Jevおまかせがコストを認識して売買頻度・保有数量を調整できるかを、期間を分けて検証する。従来のsupervisorの価値も比較対象として残す。

次の順序を推奨:

1. 十分な頻度のraw tickを蓄積し、短いおまかせreplayでcall/token/latency・約定を確認
2. 条件を固定し、別日・別区間でおまかせ / 従来Jev / code-only / No Tradeを比較
3. 値動き・spread・slippage・手数料の損益分解と、turnover・平均/最大保有額・変更頻度を確認
4. 任意制約の有無を比較し、1区間への最適化を避ける
5. 従来supervisorは採取したC-run traceを `uv run jevpip experiment --trace ...` でA/B/C/D比較
6. historical fundamentalsは観測時点のrevisionを再現できる設計を先に整える

主に見る指標:

- net PnL
- Profit Factor
- max DD
- average loss
- fee / trade count
- Jevが止めたtradeのcounterfactual result
- avoided loss
- missed profit

目的は予測精度だけでなく、コストを含む保有判断・取引頻度・risk controlに価値があるかを測ること。

## 新しいチャットへ引き継ぐ場合

最初に読むもの:

1. README.md
2. docs/CURRENT_STATE.md
3. docs/JEV_AUTOPILOT.md と DESIGN.md の Section 38
4. GitHub Issue #17（従来supervisorについては #4）

次の作業テーマ:

> Jevおまかせprototypeの会計・時刻・数量制約をreviewし、別期間のraw tickで従来モードと比較する。
