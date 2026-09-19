# JevPip

JevPip は、**TypeSafe AI の Jev** と **GMOコイン 外国為替FX API** を組み合わせた、USD/JPY向けの短期市場判断・実験システムです。

いきなり自動売買botを作るプロジェクトではありません。まず市場を観測し、raw tick、特徴量、Jevの確率判断、将来価格を保存して、Jevに本当に予測力や売買可能なedgeがあるかを検証します。

> **Live trading is not implemented.** 初期版はPublic APIだけを使い、1円も発注しません。

## Start here

実装・設計判断をする前に **[DESIGN.md](./DESIGN.md)** を読んでください。

初期の類似実装調査は [docs/RESEARCH_2026-09-19.md](./docs/RESEARCH_2026-09-19.md) にあります。

## 現在できること

- GMO FX Public WebSocket用USD_JPY ticker client
- raw tickのJSONL保存
- Jev System Oneへのatomic questions
- Feature profile切替
- research signal policy切替
- GMO公式BID/ASK 1分足KLineの粗いhistorical replay
- live tradingを有効化できないsafety guard
- オフラインunit tests

## Feature profiles

Jevに何を見せるかは固定しません。

```bash
uv run jevpip features list
```

標準では次のprofileがあります。

- `minimal` — 短期価格、spread、短期move、tick activity
- `technical` — RSI / SMAを追加
- `moon_only` — **月相だけ**。価格は評価用に保持するがJevへ送らない
- `price_and_moon` — 価格 + 月相
- `random_control` — 無意味な決定論的featureだけを与える対照群
- `kitchen_sink` — 利用可能featureを広くON

独自TOMLを `--feature-config` で渡せます。

## Research signal policies

Jevの答えをLONG / SHORT / WAIT候補へ変換するruleも、Jevとは別の設定です。

```bash
uv run jevpip signals list
```

`loose` / `research_default` / `strict` を用意していますが、どれも「正しい売買閾値」ではなく比較実験の出発点です。spread制限はJevではなくcode側で判定します。

## Observer

まずraw tickだけ集める:

```bash
uv run jevpip observe --profile minimal
```

Jevも呼ぶ場合:

```bash
export TYPESAFE_API_KEY=...
uv run jevpip observe --profile minimal --with-jev
```

月だけ見せる場合:

```bash
uv run jevpip observe --profile moon_only --with-jev
```

## Historical replay

GMO公式1分足のBID/ASKを取得し、同じfeature pipelineへ流します。

```bash
uv run jevpip backtest --date 20260918 --profile technical
```

これは粗い1分足研究用です。**5秒/30秒のスキャルピング性能は検証できません。** 真の短期backtestは、今から保存するraw tickを後日replayして行います。

## Data

runtime dataは `data/` 以下へ保存され、Gitでは無視されます。

TypeSafeの現行契約にはサービスのbenchmark/performance informationの公開制限があるため、Jevの実測性能、Brier score、勝率、PnLなどは公開repositoryへcommitしない方針です。評価コード自体は公開できます。

## Development

Python 3.12 + uv:

```bash
uv sync --extra dev
uv run pytest
```

外部APIなしのunit testsを基本にします。Public WebSocket / TypeSafeのlive疎通はintegration checkとして分離します。
