# JevPip

JevPip は、**GMOの市場データを使うローカル・マーケットターミナル兼研究アプリ**です。GMO外国為替FXの対円12ペアとBTC/JPYへ対応し、TypeSafe AI の Jev は必要なときだけ追加できる判断レイヤーとして扱います。

目的は、いきなり自動売買をすることではありません。まず市場を観測し、raw tick、特徴量、Jevの確率判断、将来価格を保存して、「Jevに何を見せると、どんな判断になり、その判断は実際の値動きとどう対応するか」を検証します。

> **現在は実売買しません。** 市場データはGMOのPublic APIから取得します。外国為替FXのPrivate APIは設定した場合に口座・建玉をGETで参照するだけで、注文系POSTは実装していません。

## いちばん簡単な使い方

JevPip は Python 3.12 で動くローカルアプリです。macOS と Windows の両方で動く構成にしています。

まず Python 3.12 と [uv](https://docs.astral.sh/uv/) を用意し、このリポジトリで依存関係を入れます。

```bash
uv sync --extra dev
```

ブラウザUIを起動します。

```bash
uv run jevpip ui
```

標準では次のURLで起動し、ブラウザも自動で開きます。

```text
http://127.0.0.1:8765
```

終了するときは、起動したターミナルまたはPowerShellで `Ctrl+C` を押します。

ブラウザを自動で開きたくない場合:

```bash
uv run jevpip ui --no-open
```

### macOS

「ターミナル」で上記コマンドを実行します。

### Windows

PowerShell または Windows Terminal で同じコマンドを実行します。


## すでにclone済みの場合

新しいUIへ更新するには、JevPipディレクトリで次を実行します。

```bash
git pull
uv sync --extra dev
uv run jevpip ui
```

## ブラウザUIでできること

現在のUIは日本語です。主画面は **簡単なMT4 + TradingView** を意識した1画面ターミナルに整理し、難しい研究用パラメータは「詳細設定」に畳んでいます。中央をチャート、右を自動売買設定、下を口座・建玉・Jev・ログ系のターミナルとして使います。

- GMO外国為替FXの対円12ペアと BTC/JPY を切り替えてリアルタイム観測
- GMOの過去KLineを自動で読み込み、live tickを末尾へ接続
- 1分 / 5分 / 15分 / 1時間のチャート切替
- 過去KLineをローソク足表示し、live MIDを末尾へ接続
- MA20 / MA200 の表示切替
- BID / ASKからMIDを更新
- 「観測だけ」と「デモ取引」を切り替え
- 仮想資金・仮想ポジション・確定/含み損益をリアルタイム表示
- チャート上へデモのOPEN / CLOSEマーカーを表示
- デモ戦略を Momentum / RSI mean reversion / MA trend / Jev signal から選択
- 外国為替FX実口座の時価評価総額・残高・取引余力・評価損益・証拠金維持率・USD/JPY建玉を参照専用で表示
- Featureプリセットを「基本」「テクニカル」「月だけ」などから選択
- Jev利用のON/OFF
- 詳細設定でFeature / Signal / Paper scalpingパラメータを変更
- GMO公式BID/ASK 1分足による粗い履歴リプレイ
- tick / Jev / デモ売買イベントのログ表示

UI上で変更したカスタム設定は、現時点では恒久保存しません。

## Paper strategy

デモ自動売買では現在、次のstrategyを選べます。

- **Momentum**: 指定秒数のMID変化がthresholdを超えた方向へentry
- **RSI mean reversion**: RSIがoversoldならLONG、overboughtならSHORT
- **MA trend**: short MAとlong MAの差がthresholdを超えた方向へentry
- **Jev signal**: Jevの研究用LONG / SHORT / WAITを利用

RSI / MAのstrategy計算は、現時点では**tick本数ベース**です。MT4等で一般的な時間足barベースのRSI / MAとは意味が異なるため、UIでもtick semanticsであることを明示しています。今後bar-based strategyへ発展させます。

### Code-only safety supervisor

Paper strategyの前に、Jevを使わないdeterministic supervisorを置けます。

現在見るもの:

- market statusがOPENでない → `PAUSE_ALL`
- market timestampが古すぎる → `PAUSE_ALL`
- spreadが設定上限を超える → `PAUSE_ENTRY`
- spreadが上限の80%以上 → `CAUTION`

supervisorは**リスクを厳しくする方向にしか動けません**。数量を増やしたり、TP / SLやspread limitを緩めたりはしません。

これは将来のJev supervisorと比較するbaselineでもあります。

## Jevなしでも使える

Jevは必須ではありません。

JevをOFFにしても、次の機能は使えます。

- 対円FX 12ペア / BTC/JPY のチャート
- 過去KLineの表示
- live market観測
- raw tick保存
- 5秒モメンタム等のcode-based paper strategy
- デモ口座の残高・PnL・仮想建玉
- 対円FXペアの粗いBID/ASK KLine replay
- 外国為替FX実口座のread-only表示（認証情報を設定した場合）

つまりJevPip本体は、チャート・データ収集・paper broker・研究機能を持つ小さなターミナルとして動きます。Jevはその上に追加できるstrategy / research componentの一つです。

## 対応FXペア

現在paper PnLを日本円のまま正しく扱える、以下の対円12ペアを有効にしています。

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

GMO外国為替FX自体は非対円ペアを含む21通貨ペアを扱っていますが、EUR/USDなどはPnLをJPYへ換算するcross-rate modelが必要です。JevPipでは計算を誤魔化さず、円換算モデルを入れてから対応します。

対円FXはライブ観測・過去チャート・paper trading・1分足BID/ASK replayに利用できます。

## BTC/JPY

BTCはGMOコイン暗号資産Public APIの現物 `BTC` tickerを使います。

```text
Public REST:
https://api.coin.z.com/public

Public WebSocket:
wss://api.coin.z.com/ws/public/v1
```

BTCはメンテナンス時を除き24時間365日動くため、FX市場が閉じる週末でも観測・デモ取引を試せます。

チャートの過去足はGMO暗号資産Public RESTのKLineを使用し、現在は次を切り替えられます。

- 1min
- 5min
- 15min
- 1hour

BTCのpaper tradeでは、価格差の単位をFXのpipsではなく**円**として扱い、数量には小数BTCを使用します。初期値は研究用の仮設定であり、推奨売買条件ではありません。

## JevのAPIキー

raw tick収集やJevを使わない1分足リプレイだけなら、TypeSafeのAPIキーは不要です。

Jevを使う場合は、`.env.example` を参考に `.env` を作り、次を設定してください。

```env
TYPESAFE_API_KEY=...
```

APIキーそのものはブラウザへ返しません。


## GMO実口座を参照する

実口座表示はオプションです。設定しなくても観測・デモ取引・バックテストは使えます。

GMOコイン外国為替FXの会員ページでAPIキーを作成し、**口座情報・建玉の参照に必要な権限だけ**を与えてください。注文権限はJevPipの現在の用途には不要です。可能ならGMO側のIP制限も利用してください。

`.env` に次を追加します。

```env
GMO_FX_API_KEY=...
GMO_FX_API_SECRET=...
```

JevPipが実口座表示に使うPrivate APIは、現在この2つだけです。

```text
GET /private/v1/account/assets
GET /private/v1/openPositions?symbol=USD_JPY
```

JevPipのPrivate APIクライアント自体をGET専用として実装しており、注文系POSTエンドポイントは持っていません。APIキーとシークレットの値はブラウザへ返しません。


## Jevに見せる情報

JevPipでは「正しい指標セット」を固定しません。

標準Featureプリセット:

- `minimal` : 短期価格、spread、短期move、tick activity
- `technical` : RSI / SMAを追加
- `moon_only` : **月の満ち欠けだけ**をJevに見せる
- `price_and_moon` : 価格 + 月相
- `random_control` : 無意味な決定論的featureだけを与える対照群
- `kitchen_sink` : 利用可能featureを広くON

ブラウザUIでは、これらを選んだあとに個別設定を変更できます。

CLIで一覧を見る場合:

```bash
uv run jevpip features list
```

## 研究用シグナル

Jevには直接「買う / 売る」を決めさせません。

初期Jev questions:

- direction: UP / DOWN / FLAT
- market_is_noisy
- reversal_risk
- trend_strength

その回答を、コード側のSignal Policyで `LONG / SHORT / WAIT` 候補へ変換します。

標準Signal Policy:

- `loose`
- `research_default`
- `strict`

どれも「正しい売買設定」ではありません。比較実験の出発点です。

```bash
uv run jevpip signals list
```

## デモ取引

ブラウザUIで「デモ自動売買」を選ぶと、GMOから受信した**実際のBID / ASK**で仮想スキャルピングを行います。

売買設定は、一般的な売買画面に近い順番で **銘柄 / 注文数量 / Take Profit / Stop Loss / 最大スプレッド** を前面に出します。JevPip固有の判定時間、エントリー判定幅、再エントリー待機などは詳細設定へ分け、現在の条件を日本語の文章でも要約表示します。

現在は次の4戦略を選べます。

- **Momentum**: 直近のMID変化が設定値を超えた方向へ仮想エントリー。Jev不要
- **RSI mean reversion**: tick-count RSIがoversoldならLONG、overboughtならSHORT
- **MA trend**: tick-count short / long MAの差がthresholdを超えた方向へentry
- **Jev signal**: Jevの研究用 `LONG / SHORT / WAIT` シグナルで仮想エントリー

仮想LONGはASKで入りBIDで決済し、仮想SHORTはBIDで入りASKで決済します。そのため実際のspreadは最初から損益へ反映されます。

初期版では単一ポジションとし、利確・損切り・最大保有時間・cooldownを設定できます。

デモ損益は次のコストを含めます。

- 実際のBID / ASK spread
- BTC: 取引所現物のTaker 0.05% / 約定を参考にしたpaper fee
- 対円FX: 外国為替FX APIの約定金額 × 0.002% / 約定を参考にしたpaper fee
- 任意のadverse slippage（詳細設定。初期値0）

UIには **コスト後確定損益 / 粗利益 / 手数料 / Profit Factor / 最大ドローダウン / 勝率** を表示します。

BTCのPublic tickerは現物市場ですが、paper engineは比較研究のためLONG / SHORT両方向を許可しています。したがってBTCのSHORTは**仮想ショート**であり、現物売買そのものを再現したものではありません。

> デモ取引は将来の利益を示すものではありません。約定板の深さ、部分約定、動的slippage、資金・証拠金制約などはまだ完全にはモデル化していません。

## CLIで観測する

ブラウザUIを使わず、ターミナルだけでも動かせます。

raw tickだけ集める:

```bash
uv run jevpip observe --profile minimal
```

Jevも使う:

```bash
uv run jevpip observe --profile minimal --with-jev
```

月だけ見せる:

```bash
uv run jevpip observe --profile moon_only --with-jev
```

## Raw tickで戦略比較

ライブ観測で保存したraw tickを、**同じデータ・同じpaper cost model**で複数のcode-only strategyへ流して比較できます。

例:

```bash
uv run jevpip compare \
  --instrument BTC \
  --file data/raw_ticks/BTC/2026-09-19.jsonl
```

標準では次を比較します。

- momentum
- rsi_mean_reversion
- ma_trend

出力:

- net PnL
- Profit Factor
- max drawdown
- closed trades
- win rate
- fees paid

JSONが必要なら:

```bash
uv run jevpip compare \
  --instrument BTC \
  --file data/raw_ticks/BTC/2026-09-19.jsonl \
  --json
```

安全監督の有無も比較できます。

```bash
uv run jevpip compare \
  --instrument BTC \
  --file data/raw_ticks/BTC/2026-09-19.jsonl \
  --no-supervisor
```

このcompareはJev APIを呼びません。Jev direct / Jev supervisorとの比較は、code-only baselineを固めた後の別Phaseです。

## 1分足リプレイ

選択中の対円FXペアについて、GMO公式のBID / ASK KLineを取得し、同じFeature pipelineへ流します。BTCのhistorical KLineはBID/ASK履歴ではないため、この統計リプレイには使いません。

ブラウザUIから実行するほか、CLIでも動かせます。

```bash
uv run jevpip backtest --date 20260918 --profile technical
```

これは**粗い1分足研究用**です。

1分足だけでは60秒の中の値動き順序を復元できないため、5秒・30秒スキャルピング性能の検証には使いません。短期の精密バックテストは、今から保存するraw tickを後日replayして行います。

## データ保存

runtime dataは `data/` 以下へ保存します。

主な保存先:

```text
data/
├── raw_ticks/
│   └── <instrument>/
├── decisions/
│   └── <instrument>/
└── backtests/
```

これらはGitで無視されます。

TypeSafeの現行契約にはサービスのbenchmark / performance informationの公開制限があるため、Jevの実測accuracy、Brier score、勝率、PnL等は公開リポジトリへcommitしない方針です。評価コードや評価方法自体は公開できます。

参考:

- https://typesafe.ai/legal/mca

## Private APIのrate-limit / retry

現在の外国為替FX Private API利用はread-onlyです。

- Private GETはclient内の共有sliding-window limiterを通す
- UI側にも3秒cacheがあり、口座refresh連打でAPIを叩き続けない
- read-only GETはclient内で自動retryしない
- 一時的な失敗はエラー表示し、次回refreshへ任せる
- 将来注文POSTを追加する場合、**timeout / connection errorを理由に同じ注文をblind retryしない**
- 注文系retryを実装する前に、client order ID相当・注文照会・idempotency・最新のGMO公式rate limitを確認する

現在のPrivate clientには注文POST自体が存在しません。

## 安全方針

現時点のJevPipには、次のものはありません。

- GMO Private APIによる注文
- 実ポジションの作成・決済
- 自動実売買
- live trading

Private APIは、設定した場合に口座残高と建玉を**参照するGETのみ**実装しています。

また、`LIVE_TRADING=true` を設定すると起動時に拒否します。

Jevの出力を将来注文へつなぐ場合も、spread、market status、position limit、loss limit、stale data等はコード側の決定論的ルールで管理する方針です。

## 開発

```bash
uv sync --extra dev
uv run pytest
```

FastAPIのWeb UIはローカルホストで動きます。UI/APIのテストにはFastAPIの `TestClient` を使っています。

外部APIを使わないunit testを基本とし、GMO Public WebSocketやTypeSafeへのlive疎通はintegration checkとして分離します。

## 設計資料

実装・設計判断を変更するときは、まず [DESIGN.md](./DESIGN.md) を確認してください。

初期の類似実装調査:

- [docs/RESEARCH_2026-09-19.md](./docs/RESEARCH_2026-09-19.md)

## 現在の位置づけ

JevPipは現在、次の四つを同じローカルアプリへまとめている段階です。

1. **Market Terminal** : 対円FX 12ペア / BTC/JPY の過去チャート + live market表示
2. **Paper Broker** : Jevなしのルール戦略でも動く仮想売買・PnL
3. **Observer / Feature Lab** : raw tickを保存し、Jevへ見せる情報を組み替えて比較
4. **Backtester** : 対円FX BID/ASK KLine replayと、今後のraw tick replayで設定を再検証

Jevはこの土台を利用する任意コンポーネントです。将来、ETHや他のFX通貨ペアを追加しても、market / chart / paperの基本構造を再利用できる設計にします。
