# JevPip 設計書 / Project Handoff

> **Status:** early prototype implemented / Observer + Feature Lab + 1分足replay + local Web UI  
> **Repository:** `yo4e/JevPip`  
> **Created:** 2026-09-19  
> **Primary goal:** GMOコインの外国為替FX APIからリアルタイム市場データを受け取り、TypeSafe AI の Jev を「高速な確率付き判断器」として組み込んだ、USD/JPY向けスキャルピング研究システムを作る。  
> **Important:** 最初から実弾売買はしない。まず観測 → ログ → ペーパー売買 → 評価の順で進める。

---

## 1. このプロジェクトが生まれた経緯

Jev は TypeSafe AI が 2026-09-14 に公開した System One Model。一般的なLLMのように文章を生成するのではなく、与えられた `state` に対して、あらかじめ定義した質問へ型付きの確率的判断を返す。

主なプリミティブは以下。

- **Noul**: Yes / No。0〜1の確率を返す
- **Choice**: 定義した候補から選択。各候補の確率分布 + confidence を返す
- **Score**: 定義した段階上のスコア + 確率分布 + confidence を返す

公式ドキュメントでは、複雑な判断を一発で聞くより「一瞬で判断できる狭い質問」に分解し、複数の回答をコード側で合成する設計が推奨されている。

Jev は生成をしない代わりに、低コスト・低レイテンシで大量の曖昧判断をさばく用途を狙っている。価格は設計時点で **$0.042 / 1M input tokens**（出力は無料扱い）。

### 参考

- TypeSafe Quick Start: https://docs.typesafe.ai/introduction/quickstart
- TypeSafe Primitives: https://docs.typesafe.ai/primitives
- Jev introduction: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe homepage/pricing: https://typesafe.ai/

---

## 2. 事前に行ったJevの小実験

この実験結果は **性能保証ではなく、Jevの挙動を理解するための玩具実験**。売買戦略の根拠にはしないこと。

### 2.1 皮肉の理解

State:

```json
{
  "text": "最高の旅行だったよ。財布をなくして、飛行機に乗り遅れて、ホテルでは水漏れしたけど。"
}
```

質問: 「話者は本当に旅行に満足しているか？」

結果: **12% true**

表面的な「最高」という語だけではなく、文脈を読んで否定寄りに判断した。

### 2.2 情報ゼロのUSD/JPY予測

State:

```json
{}
```

質問: 「24時間後のUSD/JPYは現在より高いか？」

結果: **49% true**。同じ条件で再実行しても49%。

少なくともこの実験では、情報がないときに極端な自信を出さず、ほぼ50/50へ戻った。

### 2.3 月〜水だけ見せて金曜終値をChoice予測

入力した終値:

- Monday: 154.36
- Tuesday: 155.10
- Wednesday: 156.29

候補を0.5円刻みで与え、Friday closeを選ばせた。

上位結果:

- 157.5: 55%
- 157.0: 27%
- 156.5: 11%
- confidence: 50%

実際の金曜終値は約156.89。これも単発の玩具実験であり、予測力の証明ではない。

---

## 3. JevPipの目的

### 3.1 MVPの目的

**リアルタイムのUSD/JPYを観測し、Jevの判断と、その直後の実際の値動きを大量に記録する。**

最初のMVPでは注文を出さない。

狙いは、

1. Jevが短期価格情報をどう読むか
2. 確率が将来の値動きと校正されているか
3. どのstate設計・質問設計が最も有効か
4. スプレッド等の現実コスト込みで売買エッジになり得るか

を検証すること。

### 3.2 最終的に検討するもの

検証結果が十分なら、

```text
GMO Public WebSocket
        ↓
market data / feature engine
        ↓
Jev decision layer
        ↓
deterministic strategy + risk gate
        ↓
paper broker
        ↓
[明示的に有効化した場合のみ]
GMO Private API
        ↓
live order
```

まで発展させる。

**Jevの出力をそのまま注文へ直結させない。**  
必ず決定論的なstrategy/risk layerを挟む。

---

## 4. GMOコイン 外国為替FX API

暗号資産APIではなく、**外国為替FX API** を使う。

公式ドキュメント:

- https://api.coin.z.com/fxdocs/
- https://coin.z.com/jp/corp/product/info/fx/api/

### 4.1 エンドポイント

設計時点の公式値:

```text
Public REST:
https://forex-api.coin.z.com/public

Public WebSocket:
wss://forex-api.coin.z.com/ws/public

Private REST:
https://forex-api.coin.z.com/private

Private WebSocket:
wss://forex-api.coin.z.com/ws/private
```

対象はまず **USD_JPY** のみ。

### 4.2 Public WebSocket

tickerをsubscribeすると、少なくとも以下が届く。

```json
{
  "symbol": "USD_JPY",
  "ask": "...",
  "bid": "...",
  "timestamp": "...",
  "status": "OPEN"
}
```

これをJevPipの主入力にする。

### 4.3 過去データ

Public RESTにはKLineがあり、USD/JPYについて `1min` 以上のOHLCを取得できる。

ただし、**真のスキャルピング検証に必要なティック履歴を過去へ遡って再生できるとは限らない**。そのため、プロジェクト開始直後からWebSocketデータを自前保存することが重要。

粗い研究は1分足でできるが、秒〜数秒ホライズンの評価には自前収集ティックを使う。

### 4.4 API制限

外国為替FX APIの設計時点の制限:

- Public WebSocket subscribe/unsubscribe: 同一IPから1秒1回
- Private GET: 同一アカウント 6 req/s
- Private POST: 同一アカウント 1 req/s

制限値は将来変更され得るので、実装時には公式ドキュメントを再確認すること。

### 4.5 API手数料

設計時点では、

- レート取得・口座情報取得: 無料
- FX API経由の注文/注文変更が約定: **約定金額 × 0.002%**
- 初回FX APIキー作成後30日間はAPI手数料無料

スキャルピングではこのAPI手数料、スプレッド、スリッページが致命的になり得る。**バックテスト/Paper PnLには必ず全部入れる。**

---

## 5. 推奨技術スタック

最初は **Python 3.12** を推奨。

理由:

- TypeSafe公式Python SDKがある
- GMO公式ドキュメントにPython例がある
- 非同期WebSocket + 数値処理 + ログ解析がやりやすい
- 研究用コードからそのままサービス化しやすい

候補:

- package management: `uv`
- async runtime: `asyncio`
- WebSocket: `websockets` または `aiohttp`
- HTTP: `httpx`
- Jev: `typesafe-sdk`
- config: `pydantic-settings`
- dataframe/analysis: `polars` or `pandas`
- tests: `pytest`

初期段階ではDBを必須にしない。JSONL/Parquetで十分。

---

## 6. 推奨ディレクトリ構成

```text
JevPip/
├── README.md
├── DESIGN.md
├── pyproject.toml
├── .env.example
├── src/
│   └── jevpip/
│       ├── config.py
│       ├── cli.py
│       │
│       ├── gmo/
│       │   ├── public_ws.py
│       │   ├── public_rest.py
│       │   └── private_rest.py      # live段階まで未使用でよい
│       │
│       ├── market/
│       │   ├── buffer.py
│       │   ├── aggregate.py
│       │   └── features.py
│       │
│       ├── jev/
│       │   ├── client.py
│       │   ├── state.py
│       │   └── questions.py
│       │
│       ├── strategy/
│       │   ├── signals.py
│       │   └── risk.py
│       │
│       ├── broker/
│       │   ├── base.py
│       │   ├── paper.py
│       │   └── live.py              # 後期フェーズ
│       │
│       └── storage/
│           └── event_log.py
│
├── data/
│   └── .gitkeep
└── tests/
```

---

## 7. Market State設計

Jevには生ティックを無制限に丸投げしない。

コード側で短期特徴量を作り、意味のあるstateとして渡す。

初期候補:

```json
{
  "symbol": "USD_JPY",
  "timestamp": "ISO-8601",
  "market_status": "OPEN",

  "bid": 0.0,
  "ask": 0.0,
  "mid": 0.0,
  "spread_pips": 0.0,

  "return_1s": 0.0,
  "return_3s": 0.0,
  "return_5s": 0.0,
  "return_15s": 0.0,
  "return_30s": 0.0,
  "return_60s": 0.0,

  "range_5s_pips": 0.0,
  "range_30s_pips": 0.0,
  "realized_vol_30s": 0.0,
  "tick_count_5s": 0,
  "tick_count_30s": 0,

  "recent_mid_samples": [],
  "session": "tokyo|london|new_york|overlap"
}
```

特徴量は増やしすぎない。まず単純なものから始め、A/B比較する。

**APIキー、APIシークレット、口座残高などはJev stateへ送らない。**

---

## 8. Jev質問設計

TypeSafeの推奨に合わせ、巨大な「買うべき？」1問だけにしない。

同じstateに対して複数質問を一括送信する。

初期案:

### direction_5s / Choice

```text
Based only on the supplied market state, what is the most likely USD/JPY direction over the next 5 seconds?

UP
DOWN
FLAT
```

### direction_30s / Choice

同様に30秒先。

### trend_strength / Score

例:

1. no meaningful directional trend
2. weak
3. moderate
4. strong

### reversal_risk / Noul

```text
Does the current short-term move show a meaningful risk of reversing within the next 10 seconds?
```

### market_is_noisy / Noul

```text
Is the current short-term price action too noisy or directionless for a directional entry?
```

### action_hint / Choice（研究用）

```text
LONG / SHORT / WAIT
```

これは記録・比較用。**action_hint単独で発注しない。**

### コード側で処理すべきもの

以下は曖昧判断ではないのでJevに聞かずコードで決める。

- spread <= threshold
- market status == OPEN
- cooldown
- max position
- daily loss limit
- order rate limit
- stop loss / emergency stop
- stale data detection
- API health

「AIが判断すべきこと」と「普通のif文で確実に決めること」を分離する。

---

## 9. 初期のstrategy案

MVPでは **予測の観測だけ** でよい。

Paper Tradingに進む場合の一例:

```text
LONG candidate:
  direction_5s.UP >= threshold
  AND market_is_noisy < threshold
  AND reversal_risk < threshold
  AND spread <= max_spread
  AND cooldown clear

SHORT candidate:
  対称条件

otherwise:
  WAIT
```

thresholdは固定せず、収集データで後から検証する。

Jevのconfidence自体を「真実」と扱わない。実際の将来リターンとの**calibration**を測る。

---

## 10. データ記録

このプロジェクトで一番重要なのは、最初の売買ロジックより**データセットを作ること**。

1 decision eventにつき最低限:

```json
{
  "event_id": "...",
  "received_at": "...",
  "market_timestamp": "...",

  "raw_bid": 0.0,
  "raw_ask": 0.0,
  "features": {},

  "jev_model": "jev-latest",
  "jev_answers": {},
  "jev_input_tokens": 0,
  "jev_latency_ms": 0,

  "strategy_decision": "LONG|SHORT|WAIT",

  "future_mid_1s": null,
  "future_mid_5s": null,
  "future_mid_10s": null,
  "future_mid_30s": null,
  "future_mid_60s": null,

  "paper_trade": null
}
```

将来価格は後から埋めてもよい。

JSONLで開始し、まとまったらParquet化する。

---

## 11. 評価指標

「的中率」だけを見ない。

### 予測性能

- direction accuracy
- Brier score
- calibration curve
- log loss
- horizon別 accuracy (1s / 5s / 10s / 30s / 60s)
- confidence bucket別成績

### 売買性能

- gross PnL
- **net PnL after spread**
- **net PnL after GMO API fee**
- simulated slippage込みPnL
- win rate
- profit factor
- max drawdown
- trades/day
- turnover
- average holding time

### システム性能

- GMO tick → Jev request latency
- Jev response latency
- full decision-loop latency
- dropped/stale ticks
- reconnect count
- Jev cost / day

---

## 12. フェーズ分け

### Phase 0: Connectivity

目的:

- GMO Public WebSocketでUSD_JPY tickerを受信
- ローカルへ保存
- Jev APIを1回呼べる

**注文機能なし。**

### Phase 1: Observer

- tick buffer
- feature generation
- 1秒程度の configurable cadence でJev判定
- 全判定を保存
- 未来価格を付与
- dashboard不要。CLI/logでよい

### Phase 2: Evaluation

- 数日〜数週間データ収集
- calibration、horizon別精度を測定
- state/questionを比較
- Jevあり vs 単純baseline（momentum、random、moving average等）を必ず比較

Jevが単純ルールに勝てないなら、その事実を受け入れる。

### Phase 3: Paper Trading

- 仮想ポジション
- spreadを実レートから反映
- API fee相当もコストとして計上
- slippageモデル導入
- risk gate
- kill switch

### Phase 4: Shadow Live

Private APIは口座/注文状態確認に使っても、**注文しない**。

実運用時のAPI遅延・状態同期を確認。

### Phase 5: Tiny Live（検証が良好な場合のみ）

- 明示的な `LIVE_TRADING=true` が必要
- デフォルトfalse
- GMO公式の最小注文数量を確認
- ハードな最大ポジション
- 1日最大損失
- 連敗停止
- 最大トレード回数
- emergency stop
- 起動直後は注文禁止、状態同期後にarmする

---

## 13. セキュリティ

絶対条件:

- `TYPESAFE_API_KEY` をGitへcommitしない
- GMO API key / secretをcommitしない
- `.env` をgitignore
- `.env.example` には名前だけ
- GitHub Actionsを使う場合はSecretsを使用
- GMO Private API keyは必要最小限のpermission
- ログへAPI secret/header/signatureを出さない
- Public repo前提で設計する

Live tradingを実装するまでは、GMO Private API key自体を要求しない構成が理想。

---

## 14. 運用場所

**GitHub Actionsを常時スキャルピング実行基盤にはしない。**

ActionsはCI/定期テスト向けで、低遅延・常時WebSocket接続には不向き。

開発中:

- local Mac
- Codespaces（短時間テスト）

常時運用候補:

- VPS
- small cloud VM
- container service with persistent process

遅延を測ってから決める。

---

## 15. 既存GitHub状況（2026-09-19調査）

GitHub上には、

- GMO FX APIのPython client
- GMOコイン向け自動売買bot
- Jevを使うtrading系prototype

はすでに存在する。

一方、2026-09-19時点で、

- `Jev GMO`
- `Jev GMOコイン`
- `Jev api.coin.z.com`
- `typesafe-sdk GMO`
- `jev-latest GMO`

等で公開GitHubを検索した範囲では、**Jev + GMOコイン外国為替FX APIを組み合わせた公開実装は確認できなかった。**

したがってJevPipはかなり早い公開実装になり得る。ただし、GitHub検索で見つからなかっただけなので **「世界初」などの断定はしないこと。**

参考として確認済み:

- https://github.com/ajim3796/gmo_coin_fx_api
- https://github.com/RikitoNoto/gmo-fx-py

---

## 16. MVPのDefinition of Done

最初の実装で、これだけできれば成功。

```text
$ jevpip observe
Connected to GMO FX WebSocket
USD_JPY bid=... ask=... spread=...
Jev:
  direction_5s:
    UP 0.xx
    DOWN 0.xx
    FLAT 0.xx
  reversal_risk: 0.xx
  market_is_noisy: 0.xx
Saved event: data/events/....
```

そして24時間程度走らせた後、

```text
$ jevpip evaluate
samples: ...
direction_5s_accuracy: ...
brier_score: ...
calibration: ...
jev_cost: ...
```

を出せること。

**この段階では1円も売買しなくてよい。**

---

## 17. 実装時の優先順位

1. GMO Public WebSocketが安定して取れる
2. Raw tickを必ず保存する
3. feature計算
4. Jev API接続
5. decision log
6. future outcome付与
7. evaluation
8. paper trading
9. Private API
10. live trading

UIや豪華なdashboardは後回し。

---

## 18. 次のチャット / 実装担当への申し送り

このリポジトリを開いたAI/開発者は、いきなりbotを完成させようとしないこと。

まず **Phase 0 + Phase 1** を実装する。

最初のPRまたはコミットで推奨する範囲:

1. Python project skeleton
2. `.gitignore`
3. `.env.example`
4. GMO FX Public WebSocket client
5. USD_JPY tick logger
6. TypeSafe/Jev client
7. minimal feature builder
8. Jev question schema
9. observer CLI
10. tests

**Live order codeはまだ不要。**

また、実装開始時には必ずTypeSafeとGMOの最新公式仕様を再取得し、この設計書の料金・制限・SDK仕様が変わっていないか確認すること。

---

## 19. 一行で言うと

**JevPip = USD/JPYのリアルタイム市場状態をJevに読ませ、確率付き短期判断を大量収集・検証し、十分な根拠が得られた場合だけペーパー売買から段階的に自動売買へ進む研究プロジェクト。**


---

## 20. 実装開始時の追加決定（2026-09-19）

初期競合調査と実装検討により、以下を正式方針として追加する。

### 20.1 Feature Lab

Jevに渡す市場情報は一つの固定セットにしない。

Feature profileで、各入力を独立にON/OFFできる構造とする。

初期profile:

- `minimal`
- `technical`
- `moon_only`
- `price_and_moon`
- `random_control`
- `kitchen_sink`

月相のような非典型featureも、仮説として排除しない。重要なのは「常識的か」ではなく、同じfuture outcomeに対して公平に比較できること。

`moon_only` では市場価格を評価用には保持するが、Jev stateには送らない。

`random_control` は、無意味な入力に対してJevがもっともらしい確信を形成していないかを見るnegative controlとして使う。

Feature configurationとJev questionsは独立させる。同じ質問を、異なるfeature setへ適用して比較可能にする。

### 20.2 Jev questions と signal rule の分離

初期Jev questionsは次を基本とする。

- direction: UP / DOWN / FLAT
- market_is_noisy
- reversal_risk
- trend_strength

Jevへ直接 `LONG / SHORT / WAIT` を尋ねる方式は初期標準から外す。

Jev answerをresearch signalへ変換するthresholdは、別のSignal Policyとして設定する。

例:

- minimum direction probability
- UP/DOWN probability margin
- maximum noise probability
- maximum reversal probability
- minimum trend strength
- maximum spread

signal thresholdは正解として固定しない。収集データ上で複数設定を比較する。

spread、market status、stale data、安全制約等は引き続きcode-owned ruleとする。

### 20.3 Backtestを二層に分ける

#### Historical KLine replay

GMO外国為替FX Public RESTのBID/ASK KLineを使い、1分足以上の粗いhistorical replayを行う。

これは、

- technical featureの動作確認
- 月相等の長い時間軸の仮説
- BID/ASKを使ったspread込みoutcome計算
- feature pipelineの検証

には使える。

一方、1分足では5秒/30秒のpathは再構成できないため、短期scalping性能の証拠には使わない。

#### Raw tick replay

Phase 0から保存するPublic WebSocket raw tickを、将来の精密backtest datasetとする。

同一tick列へ複数feature profile / signal policyを適用し、公平に比較する。

### 20.4 予測結果と売買可能edgeを分離する

future outcomeにはmidだけでなくBID/ASKを保持する。

LONGの実質edgeは概念的に、

```text
future_bid - current_ask
```

SHORTの実質edgeは、

```text
current_bid - future_ask
```

で評価する。

「方向は当たったがspreadを越えられない」を明示的に区別する。

### 20.5 TypeSafe performance resultsは公開しない

2026-09-19時点の TypeSafe Master Customer Agreement 2.3(f) は、Servicesについてbenchmarkまたはperformance informationをpublishすることを禁止している。

そのため、

- 評価コード・計算方法・schemaはpublic repoへ置いてよい
- Jevの実測accuracy、Brier score、calibration、PnL等はpublic repoへcommitしない
- 実測結果はgit-ignoredなlocal dataとして扱う

を正式運用とする。

参考:
https://typesafe.ai/legal/mca

### 20.6 UI言語

初期ユーザー向けUI/CLI表記は日本語を基本とする。

GMOコイン外国為替FX APIを対象とした日本向けツールであることを優先し、初期段階でi18nを実装しない。

ただしcode identifier、data field、API boundaryは英語を維持し、将来の翻訳を妨げない構造とする。

### 20.7 類似実装調査

実装開始前調査の詳細は `docs/RESEARCH_2026-09-19.md` を参照。



---

## 21. ローカルWeb UI v0.1（2026-09-19）

CLIだけではFeature / Signal設定の実験が煩雑になるため、初期段階でローカルWeb UIを追加した。

### 21.1 起動方式

```text
uv run jevpip ui
        ↓
127.0.0.1:8765
        ↓
Safari / Chrome / Edge 等
```

JevPip本体はローカルのPython processとして動き、ブラウザは操作盤として使う。

macOS / Windowsで同じUIを使えることを優先する。

CLIは削除せず、automation / debugging / headless運用向けとして残す。

### 21.2 UI v0.1の範囲

- Observer開始 / 停止
- Feature preset選択
- Featureの個別ON/OFF・時間窓変更
- Jev ON/OFF
- Jev cadence変更
- Signal Policy preset選択
- Signal thresholdの個別変更
- 最新BID / ASK / spread表示
- 最新Jev decision表示
- GMO公式1分足KLine replay
- 直近イベント表示

UIで変更したcustom設定はv0.1では永続化しない。

### 21.3 UIの安全境界

- localhostを標準bind先にする
- TypeSafe API keyの値をブラウザへ返さない
- GMO Private APIをUIから利用しない
- 注文UIを作らない
- `LIVE_TRADING=true` は引き続き拒否する
- ブラウザ上の `LONG / SHORT / WAIT` は研究用labelであり注文ではない

### 21.4 実装

初期UIはFastAPI + vanilla HTML/CSS/JavaScriptとする。

React等のSPA frameworkは現時点では導入しない。Feature Labの操作性や画面構成が固まってから必要性を判断する。

`jevpip ui` がUvicornを起動し、標準ではブラウザを自動で開く。

### 21.5 README / UI言語

READMEと初期UIは日本語を基本とする。

コード識別子・データfield・外部API boundaryは英語を維持する。


---

## 22. Dashboard / Paper / Read-only Account（2026-09-19）

### 22.1 Dashboard-first UI

UI v0.2では、Feature設定を主画面から退避し、次を最初に見せる。

- USD/JPY realtime chart
- current MID / spread
- Observer status
- Jev research signal
- demo account equity / PnL
- real account equity / PnL（credentials設定時のみ）

ユーザーが最初に触る設定は、

- 観測だけ / デモ取引
- Feature preset
- Jev ON / OFF
- demo strategy

に絞る。

Feature windows、Signal Policy、paper risk parametersは「詳細設定」に畳む。

### 22.2 Realtime chart

Observerが受け取ったGMO Public WebSocketのBID / ASKからMIDを作り、UIへrecent pointsを渡す。

チャートにはpaper brokerのOPEN / CLOSEをmarkerとして重ねる。

初期実装は外部chart libraryを増やさず、browser Canvasで描画する。

### 22.3 Paper scalper

Paper tradingは実口座・GMO Private order APIと完全に分離する。

初期条件:

- virtual initial balance
- one position at a time
- configurable currency size
- LONG entry = current ASK
- LONG exit = current BID
- SHORT entry = current BID
- SHORT exit = current ASK
- take profit
- stop loss
- max holding seconds
- cooldown
- max spread

これによりspreadは自然に損益へ含まれる。

初期strategy:

1. `momentum`
   - recent MIDの変化がthresholdを超えた方向へ仮想entry
   - Jev不要
2. `jev`
   - code-side Signal Policyが返した `LONG / SHORT / WAIT` research labelを利用
   - 古いsignalは利用しない

API手数料とslippageはv0.2では未モデル。UIにその事実を明示する。

Paper resultsはprediction quality / live profitabilityの証拠として扱わない。

### 22.4 GMO FX Private APIの参照専用利用

実口座表示のため、以下のGETだけを実装する。

```text
GET /private/v1/account/assets
GET /private/v1/openPositions?symbol=USD_JPY
```

表示対象:

- equity
- availableAmount
- balance
- estimatedTradeFee
- margin
- marginRatio
- positionLossGain
- totalSwap
- transferableAmount
- USD/JPY open positions

認証情報はlocal `.env` に保存し、browserへAPI key / secretの値を返さない。

Private clientはGET専用classとして実装し、order / close / change / cancel等のPOST methodを持たせない。

API keyはGMO会員ページで必要最小限の参照permissionに限定する。可能ならGMO側IP制限も使用する。

### 22.5 Safety invariant

この変更後も、以下は不変。

- `LIVE_TRADING=true` は起動拒否
- live order codeなし
- Private order endpointなし
- demo tradeはlocal simulation
- UIのLONG / SHORTはresearch / paper label
- real account cardはread-only


---

## 23. Multi-Instrument Terminal / BTC（2026-09-19）

### 23.1 Jevをoptional componentへ位置づける

JevPipのcoreをJevそのものへ依存させない。

core:

```text
instrument
  ↓
GMO public market data
  ↓
history + live chart
  ↓
feature / data collection
  ↓
paper broker
```

optional:

```text
feature state
  ↓
Jev
  ↓
research signal
  ↓
paper broker
```

これにより、Jev OFFでもmarket terminal / paper trading / data collectionとして利用できる。

Jevの有効性は、同じ土台でcode-only baselineと比較する。

### 23.2 Instrument registry

銘柄固有情報は `instruments.py` に集約する。

初期instrument:

- `USD_JPY`
  - GMO外国為替FX
  - display: `USD/JPY`
  - move unit: pips
  - price unit: 0.01 JPY
- `BTC`
  - GMOコイン取引所現物 Public API
  - display: `BTC/JPY`
  - move unit: JPY
  - price unit: 1 JPY

instrumentは少なくとも次を所有する。

- API symbol
- market kind
- WebSocket endpoint
- display symbol
- price/move unit
- price decimals
- paper quantity label
- paper experiment defaults

今後のETHや他FX pairはregistry追加を基本とし、Observer/UI/Paper brokerへ個別分岐を散らさない。

### 23.3 BTC Public API

BTC現物ticker:

```text
wss://api.coin.z.com/ws/public/v1
channel=ticker
symbol=BTC
```

historical KLine:

```text
GET https://api.coin.z.com/public/v1/klines
symbol=BTC
interval=1min|5min|15min|1hour
date=YYYYMMDD
```

BTCはGMOのメンテナンス時間を除き24時間365日取引されるため、週末のlive observation targetとしても利用できる。

### 23.4 Historical chart backfill

Dashboard chartは観測開始時点からのtickだけにしない。

```text
GMO KLine history
       ↓
canvas chart
       ↓
latest candle
       ↓
live WebSocket MID
```

UI初期interval:

- 1min
- 5min
- 15min
- 1hour

history APIが指定日に空の場合は、まず前日へ1回fallbackする。

BTCのhistorical KLineはOHLC取引データでありBID/ASK履歴ではないため、これだけでspread込みscalping backtestを行わない。

### 23.5 Generic move units

USD/JPYのpipsを全marketへ流用しない。

`MarketTick` はinstrument固有の `price_unit` / `move_unit_label` を持つ。

- USD/JPY: 0.01 JPY = 1 pip
- BTC: 1 JPY = 1 move unit

Feature stateも `move_units` / `range_units` 等のgeneric schemaへ移行し、unit labelを明示する。

Paper brokerも同じprice unitでmomentum / take profit / stop lossを評価する。

### 23.6 Strict feature isolation

instrument / timestampはobserver event metadataとして保存する。

Jevへ渡すstateへは、Feature profileで明示的にONにした情報だけを入れる。

したがって `moon_only` は実際にmoon featureのみ、`random_control` はrandom controlのみとなる。

### 23.7 Scope boundary

BTC v0.1で行う:

- Public ticker
- historical chart
- paper trading
- Jev optional research

まだ行わない:

- crypto Private API
- BTC実残高表示
- BTC注文
- live trading
- BTC KLineだけを用いたspread込みscalping backtest


### 22.5 Trading-like controls

Paper trading UIは研究用パラメータをそのまま露出せず、一般的な取引端末に近い情報階層へ寄せる。

主画面:

- instrument
- trading mode
- strategy
- order size
- Take Profit
- Stop Loss
- max spread
- human-readable rule summary

詳細設定:

- momentum observation window
- entry threshold
- max holding time
- re-entry cooldown
- Jev thresholds / feature settings

JevPipには現時点でmanual market/pending order executionはないため、存在しない注文機能をMT4風に見せかけない。Paper strategyが自動でentry/exitすることを明示する。
