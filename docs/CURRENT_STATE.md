# JevPip Current State

更新日: 2026-09-21

この文書は、JevPipの**現在の実装状態と次の作業境界**を短く把握するためのhandoffです。

詳細な設計判断・経緯は [../DESIGN.md](../DESIGN.md) を参照してください。

## 現在の役割

JevPipはローカルで動くmarket research terminalです。

現在の4本柱:

1. Market Terminal
2. Paper Broker
3. Observer / Feature Lab
4. Backtester

paper取引の通常UIは **Jevモード / 戦略モード / スピリチュアルモード** の3タブに分離し、同時に複数の判断系を発動させない構成です。JevモードはJev専用、戦略モードはコード戦略専用、スピリチュアルモードはFifty+骨格＋月相 / 星座 / タロット / コイントスの方向源です。コイントスはJev Fifty+のrandom controlとして使います。

## UI情報設計（Issue #21）

UIは機能を削らず、判断系を混ぜない構成へ整理しています。

- primary workflowは上部の銘柄選択と、右サイドの「取引モード / Jev・戦略・スピリチュアルの3タブ / 基準数量 / 仮想残高」を中心にする
- paper時のJev API利用はJevモード選択と一体化し、戦略・スピリチュアルモードではJev APIを呼ばない
- 実行中は `Jev: デイトレ` / `戦略: RSI逆張り` / `スピ: 月相` のように現在の判断源を常時表示する
- 下部の「現在」は「デモ口座・建玉 / 最新判断 / 約定履歴・損益内訳」を中心にする
- 外国為替FX 実口座の参照表示は常時監視の主画面から外し、⚙設定内へ置く
- Feature / Signal Policy / code strategy / supervisorなどの詳細・互換設定は戦略モード内の「戦略の詳細設定・研究」へ集約する。Jev / スピリチュアルモードでは表示しない。旧Jev supervisorはさらに「比較研究用の旧設定」へ畳む
- Strategy BT / Jev BT / 戦略比較 / 統計リプレイには、使用データ・Jev API利用有無・token消費・目的を明示する
- 既存element IDとAPI contractは維持し、情報階層の変更を中心とする


## Jevモード

Jevおまかせはprimary paper workflowとして実装済みです。

共通:
- target-position方式で差分だけ約定
- 増額・部分決済・全決済・反転、加重平均建値と費用配賦
- 口座/equity・コスト・直近約定・market stateをJevへ渡す
- 必須の鮮度・資金・session/version検証
- liveとhistorical replayで同じbroker/accounting semantics
- 約定表、損益分解、保有額・turnover・tick間隔を記録
- 同時開始 / 重複API callを抑止

スタイル:
- **デイトレ**: `trader_context_v1` を利用。標準900秒（15分）ごとに10分先を再評価
- **スキャルピング**: `trader_context_v1` を利用。標準60秒ごとに30秒先を再評価。短く設定するほどtoken消費が増える
- **Fifty+**: flat時だけJevへUP / DOWNを問い合わせ、保有中はAPIを呼ばない。対称のnet TP/SLと決済後待機を使う

3スタイルとも1m / 5m / 15m / 1h、SMA / RSI / ATR、clock、account / PnL、cost、recent execution等を広く渡し、何を重視するかはJev自身へ任せる

Fifty+にはspread上限、往復コストgate、最大DD停止、FX paper leverage等のcode-owned safetyを共通適用します。live開始時はPublic historical KLineでmulti-timeframeをwarmupし、未確定future barは除外します。詳細は [JEV_AUTOPILOT.md](JEV_AUTOPILOT.md) と [FIFTY_PLUS.md](FIFTY_PLUS.md)。

有料APIでの十分な試行数による収益性検証は未完了です。コード戦略・direction/supervisor・A/B/C/Dは比較研究用として残しています。

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

historical 1min pointsをPaperBrokerへ流し、Momentum / RSI / MAをPnL評価します。

比較:
- strategy
- No Trade
- Buy & Hold

制約:
- 1min close-only execution
- intrabar high / low orderは復元しない
- BTCはhistorical BID / ASKがないため `bid = ask = close`

### Spiritual Fifty+ BT

historical 1min pointsでFifty+のexecution/accountingを再生し、方向源だけを差し替えます。

方向源:
- moon phase
- zodiac polarity
- tarot
- coin flip

Jev APIは呼びません。coin flipはrandom controlです。

### Raw tick strategy comparison

保存済みraw tickを同条件で再生します。

比較:
- No Trade
- Buy & Hold
- Momentum
- RSI
- MA

deterministic supervisor ON/OFFとbar inputを切替可能。

### Statistical replay

historical 1min dataをFeature pipelineへ流し、次の1分のmove / edgeを調べます。

strategy PnL backtestではありません。

### Jev historical replay

保存済みraw tickを優先し、なければGMO historical 1分足へfallbackして、現在のJevを過去market stateへ再実行します。Jev APIを実際に呼ぶためtokenを消費します。

### A/B/C/D experiment

保存済みdecision traceを使い、technical / deterministic supervisor / Jev supervisor / recorded Jev directionを同じmarket path・cost model上で比較します。Jevへは再問い合わせしません。

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

- Jev historical replayは保存済みraw tickを優先し、未保存日はGMO historical 1分足へfallback
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

- raw tickがある日は高解像度raw replayを優先する
- raw tickがない日の1分足fallbackはintraminute path / 細かいspread変化 / 秒単位entryを再現しない
- BTC historical fallbackは `bid = ask = close` 近似
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

live order導入を検討する場合だけ残るもの:
- POST limiter
- idempotency
- reconnect order/account synchronization
- POST retry policy

現行scopeではlive tradingを実装しないため、急いで進めない。

### Issue #5

Non-JPY FX pairs with historical cross-rate JPY accounting.

未着手。対円FX 12ペアで研究できるため優先度は低い。

### Issue #32

BTC現物paperと暗号資産FX paperの分離。

当面は **BTC現物paper = 1x固定 / SHORTはsynthetic** を維持する。暗号資産FX paperが必要になった時だけ、margin / fee / liquidation modelを別商品として設計する。

### Fifty+ comparison experiment

次の検証ではJev Fifty+とcoin flipを、同じmarket path・quantity・勝負幅・fee / slippage・spread gate・DD ruleで比較する。

単発のcoin flip結果ではなく、複数seed / 複数期間でrandom controlの分布を見る設計を優先する。

## 次の大きなテーマ

**Fifty+を含むJevおまかせのpaper検証を、十分な試行数と別期間で行う。**

Fifty+は1ポジションずつ持ち、決済後の待機を挟んでJevへUP / DOWNだけを聞くため、従来のおまかせより「方向判定そのもの」を観察しやすい。短期の含み益・勝率だけで判断せず、ランダム方向や従来モードと同条件で比較する。

次の順序を推奨:

1. Fifty+を複数銘柄・複数時間帯でpaper運転し、ラウンド数とraw tickを蓄積
2. 勝負幅を固定した区間を残し、UP / DOWN勝率、net PnL、fee / spread / slippage、1ラウンド所要時間を確認
3. 別日・別区間でも同じ傾向が再現するか確認
4. coin flip random controlを複数seedで回し、code-only / 従来Jevも含めてbaseline比較し、50%超過が偶然や相場偏りでないかを見る
5. 従来supervisorは採取したC-run traceを `uv run jevpip experiment --trace ...` でA/B/C/D比較
6. historical fundamentalsは観測時点のrevisionを再現できる設計を先に整える

主に見る指標:

- Fifty+ round count / win rate
- net PnL / Profit Factor / max DD
- fee / spread / slippage
- 平均ラウンド時間
- 銘柄・時間帯ごとの偏り
- coin flip random control / code-only / 従来Jevとの差
- Jev call / token効率

目的は、一時的な含み益ではなく、**Fifty+の方向二択に再現性のある50%超過があるか**、またコスト込みで研究価値が残るかを確認すること。

## 新しいチャットへ引き継ぐ場合

最初に読むもの:

1. README.md
2. docs/CURRENT_STATE.md
3. docs/JEV_AUTOPILOT.md
4. docs/FIFTY_PLUS.md
5. 必要な場合だけ DESIGN.md の該当Section

主要な完了Issue:
- #4: technical strategy / supervisor / A-B-C-D
- #17: Jevおまかせ
- #21: UI情報設計
- #22: daytrade / scalp / Fifty+

現在の主なopen work:
- #3: live orderを将来検討する場合の運用制約
- #5: non-JPY FXのJPY accounting
- #32: BTC暗号資産FX paperの将来設計
- Fifty+ direction-source comparison

次の作業テーマ:

> Jev Fifty+とcoin flip random controlを、同じmarket path / cost modelで比較できるexperimentへ整理し、十分な試行数で検証する。
