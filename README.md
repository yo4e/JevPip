# JevPip

JevPip は、**TypeSafe AI の Jev** と **GMOコイン 外国為替FX API** を組み合わせた、USD/JPY向けの短期市場研究アプリです。

目的は、いきなり自動売買をすることではありません。まず市場を観測し、raw tick、特徴量、Jevの確率判断、将来価格を保存して、「Jevに何を見せると、どんな判断になり、その判断は実際の値動きとどう対応するか」を検証します。

> **現在は実売買しません。** GMOのPublic APIだけを使い、注文機能もPrivate API接続もありません。

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

## ブラウザUIでできること

現在のUIは日本語です。

- GMO外国為替FXのUSD/JPY観測を開始・停止
- Jevに見せる特徴量をON/OFF
- Featureプリセットを選択して、その場で内容を変更
- Jev利用のON/OFF
- Jev判定間隔の変更
- LONG / SHORT / WAIT候補へ変換するシグナル閾値の変更
- 最新BID / ASK / spreadの表示
- 最新Jev判断の表示
- GMO公式BID/ASK 1分足による粗い履歴リプレイ
- この起動中の最新イベントログ表示

設定は実験用です。現時点ではUI上で変更したカスタム設定を恒久保存しません。

## JevのAPIキー

raw tick収集やJevを使わない1分足リプレイだけなら、TypeSafeのAPIキーは不要です。

Jevを使う場合は、`.env.example` を参考に `.env` を作り、次を設定してください。

```env
TYPESAFE_API_KEY=...
```

APIキーそのものはブラウザへ返しません。

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
├── decisions/
└── backtests/
```

これらはGitで無視されます。

TypeSafeの現行契約にはサービスのbenchmark / performance informationの公開制限があるため、Jevの実測accuracy、Brier score、勝率、PnL等は公開リポジトリへcommitしない方針です。評価コードや評価方法自体は公開できます。

参考:

- https://typesafe.ai/legal/mca

## 安全方針

現時点のJevPipには、次のものはありません。

- GMO Private API接続
- 注文作成
- ポジション管理
- 自動売買
- live trading

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

JevPipは現在、次の三本柱を育てている段階です。

1. **Observer** : リアルタイム市場を観測してraw tickとJev判断を蓄積
2. **Feature Lab** : Jevに見せる情報を自由に組み替えて比較
3. **Backtester** : 同じ市場データでFeature / Signal設定を再検証

月相だけでドル円を読む実験も、RSI全部盛りも、ランダム対照群も、同じ仕組みで比較できることを目指します。
