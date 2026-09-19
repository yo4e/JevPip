# JevPip

JevPip は、**GMOの市場データを使うローカル・マーケットターミナル兼研究アプリ**です。USD/JPYに加えてBTC/JPYへ対応し、TypeSafe AI の Jev は必要なときだけ追加できる判断レイヤーとして扱います。

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

現在のUIは日本語です。主画面はリアルタイムチャート中心に整理し、難しい研究用パラメータは「詳細設定」に畳んでいます。

- USD/JPY と BTC/JPY を切り替えてリアルタイム観測
- GMOの過去KLineを自動で読み込み、live tickを末尾へ接続
- 1分 / 5分 / 15分 / 1時間のチャート切替
- BID / ASKからMIDチャートを描画
- 「観測だけ」と「デモ取引」を切り替え
- 仮想資金・仮想ポジション・確定/含み損益をリアルタイム表示
- チャート上へデモのOPEN / CLOSEマーカーを表示
- デモ戦略を「5秒モメンタム」または「Jevシグナル」から選択
- 外国為替FX実口座の時価評価総額・残高・取引余力・評価損益・証拠金維持率・USD/JPY建玉を参照専用で表示
- Featureプリセットを「基本」「テクニカル」「月だけ」などから選択
- Jev利用のON/OFF
- 詳細設定でFeature / Signal / Paper scalpingパラメータを変更
- GMO公式BID/ASK 1分足による粗い履歴リプレイ
- tick / Jev / デモ売買イベントのログ表示

UI上で変更したカスタム設定は、現時点では恒久保存しません。

## Jevなしでも使える

Jevは必須ではありません。

JevをOFFにしても、次の機能は使えます。

- USD/JPY / BTC/JPY のチャート
- 過去KLineの表示
- live market観測
- raw tick保存
- 5秒モメンタム等のcode-based paper strategy
- デモ口座の残高・PnL・仮想建玉
- USD/JPYの粗いKLine replay
- 外国為替FX実口座のread-only表示（認証情報を設定した場合）

つまりJevPip本体は、チャート・データ収集・paper broker・研究機能を持つ小さなターミナルとして動きます。Jevはその上に追加できるstrategy / research componentの一つです。

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

初期状態では次の2戦略を選べます。

- **5秒モメンタム**: 直近5秒のMID変化が設定値を超えた方向へ仮想エントリー。Jev不要
- **Jevシグナル**: Jevの研究用 `LONG / SHORT / WAIT` シグナルで仮想エントリー

仮想LONGはASKで入りBIDで決済し、仮想SHORTはBIDで入りASKで決済します。そのため実際のspreadは最初から損益へ反映されます。

初期版では単一ポジションとし、利確・損切り・最大保有時間・cooldownを設定できます。

> デモ取引は将来の利益を示すものではありません。現在はAPI手数料とslippageをまだモデル化していないため、実取引より有利に見える場合があります。

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

## 1分足リプレイ

GMO公式のBID / ASK KLineを取得し、同じFeature pipelineへ流します。

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
│   ├── USD_JPY/
│   └── BTC/
├── decisions/
│   ├── USD_JPY/
│   └── BTC/
└── backtests/
```

これらはGitで無視されます。

TypeSafeの現行契約にはサービスのbenchmark / performance informationの公開制限があるため、Jevの実測accuracy、Brier score、勝率、PnL等は公開リポジトリへcommitしない方針です。評価コードや評価方法自体は公開できます。

参考:

- https://typesafe.ai/legal/mca

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

1. **Market Terminal** : USD/JPY / BTC/JPY の過去チャート + live market表示
2. **Paper Broker** : Jevなしのルール戦略でも動く仮想売買・PnL
3. **Observer / Feature Lab** : raw tickを保存し、Jevへ見せる情報を組み替えて比較
4. **Backtester** : USD/JPY KLine replayと、今後のraw tick replayで設定を再検証

Jevはこの土台を利用する任意コンポーネントです。将来、ETHや他のFX通貨ペアを追加しても、market / chart / paperの基本構造を再利用できる設計にします。
