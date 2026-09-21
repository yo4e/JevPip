# Backtest / Replay / Comparison taxonomy

JevPip の検証機能は、実装の追加順ではなく **何を検証するか** で分類する。

この文書は、今後「過去データを使う機能」を追加するたびに新しい独立BTを増やさないための基準とする。

## 1. Performance backtests

売買判断を過去のmarket pathへ流し、paper accountingでPnLを評価するもの。

現在:

- **戦略BT**
  - 判断源: Momentum / RSI mean reversion / MA trend
  - execution: `PaperBroker`
  - source: GMO historical 1分足
- **スピBT**
  - 判断源: 月相 / 星座 / タロット / コイントス
  - execution: Fifty+ / `AutopilotBroker`
  - source: GMO historical 1分足
- **Jev BT**
  - 判断源: 現在のJev
  - execution: Jev mode / Fifty+を含むpaper broker
  - source: 保存済みraw tick優先、なければGMO historical 1分足
  - Jev APIを実際に呼ぶ

共通して見る指標は、可能な限り同じ名前と意味にする。

- net PnL
- realized / gross realized PnL
- fee / slippage cost
- Profit Factor
- max drawdown
- trade count
- win rate
- average trade
- exit reasons

historical 1分足を使う場合、足内の価格経路は復元しない。FXはBID/ASK close、BTCは `bid = ask = close` の近似を明示する。

### 共通実装

historical paper backtestの機械的な処理は `src/jevpip/backtest/common.py` に集約する。

- historical point → broker event
- finite sampleの最終決済
- 共通PnL summary
- No Trade / Buy & Hold baseline
- paper trade抽出

判断源固有の設定や追加指標は、各runner側に残す。

## 2. Comparison experiments

**同じmarket path / cost model上で、複数の判断源・介入条件を横並び比較するもの。**

現在:

- **戦略比較**
  - 保存済みraw tick上でcode strategyを比較
- **A/B/C/D experiment**
  - decision trace上でtechnical / supervisor / Jev介入をcounterfactual比較

今後、比較対象が増えても原則として「新しいBT画面」を追加せず、この分類へ置く。

### Fifty+ direction-source comparison

Jev Fifty+がrandom controlを安定して上回るかを見る検証はここへ置く。

最低限、同一条件を固定する。

- instrument
- market path
- start / end
- quantity
- initial balance
- Fifty+ target
- reentry wait
- spread gate
- fee / slippage
- leverage / margin model
- max drawdown rule

比較する方向源の例:

- Jev
- coin flip
- 必要なら moon / zodiac / tarot

重要なのは **方向源以外を同じにすること**。

コイントスは1回のrunではばらつきが大きいため、単発の勝率・PnLだけでJevとの差を判断しない。将来の比較runnerでは、同じmarket pathに対して複数seedのrandom controlを実行できる構造を優先する。

この比較を実装するときは、既存のFifty+ execution / accountingを再利用し、Jev専用BTとスピBTの結果を画面上で手作業比較する構造にはしない。

## 3. Statistical replay

売買PnLを評価せず、historical dataをfeature pipelineへ通して次の値動きやedgeを集計するもの。

現在のUI名:

- **統計リプレイ**

これはperformance backtestではない。

正規API:

`POST /api/statistical-replay`

旧 `POST /api/backtest` は互換入口として残すが、新しい実装やUIからは使用しない。

コード上も `run_statistical_replay()` を正規名とし、旧 `replay_kline()` は互換aliasとして扱う。

## 4. Orthogonal dimensions

「BTの種類」を増やす前に、次の独立軸へ分解できないか確認する。

### Data source

- GMO historical 1m
- recorded raw tick
- decision trace

### Decision source

- code strategy
- Jev
- moon / zodiac / tarot
- random control

### Execution policy

- standard paper strategy
- Fifty+
- recorded/counterfactual policy

### Analysis purpose

- performance backtest
- comparison experiment
- statistical replay

新機能が既存軸の組み合わせで表現できるなら、トップレベル機能を増やさない。

## 5. UI boundary

現時点では大きなUI再設計は行わない。

既存の下部タブ:

- BACKTEST: 戦略BT / スピBT / Jev BT
- RESEARCH: 戦略比較 / 統計リプレイ / ログ

は、上記分類と大きく矛盾していない。

今後、Fifty+比較experimentを追加するときは、タブを無条件に増やさず、

- 既存の比較画面へ統合する
- 比較系をまとめた画面へ再編する

のどちらかを先に検討する。

レイアウト、タブ名、情報密度などの目視判断が必要になった段階でDesktop UIレビューへ回す。

## 6. Compatibility policy

今回の整理は既存の研究結果の意味を変えない。

- broker accountingを変更しない
- fee / slippage semanticsを変更しない
- baseline計算を変更しない
- historical data semanticsを変更しない
- Jev API call semanticsを変更しない
- 実注文を追加しない

古い名前やAPIは、容易に互換を保てるものはaliasとして残し、新規コードだけ正規名へ寄せる。
