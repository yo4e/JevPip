# Fifty+

Fifty+ は、「方向予想に50%を少し超える優位性があれば、1:1の利確・損切りでも期待値を作れるのではないか」を検証するための実験的なpaper strategyです。

## 原型

基本ルールは単純です。

1. 常に1つだけポジションを持つ。
2. ポジションがない時だけ、次の勝負の方向を決める。
3. 利確幅と損切り幅は同じにする。
4. TPまたはSLで決済されたら、すぐ次の方向を決めて次の1ポジションへ進む。
5. 方向判断の精度が50%を継続的に上回るかを観察する。

「高精度な複雑戦略を作る」よりも、「UP / DOWN の二択へ少しだけ情報優位を加える」ことを研究対象にします。

## JevPip版

JevPipでは、Jevを方向判定器として使います。

- Jevの選択肢は `UP` / `DOWN` の二択だけ。
- `UP` は基準数量のLONG。
- `DOWN` は基準数量のSHORT。
- `FLAT` / `KEEP` / `COST_TOO_HIGH` などの棄権はありません。
- ポジション保有中はJev APIを呼びません。
- TPまたはSLで決済され、次のラウンドが始まる時だけJevを呼びます。
- Jevへは直近tickと短い価格履歴を中心に渡します。
- 口座残高、取引コスト、任意制約は方向選択の材料から外し、売買ルールはbroker側で管理します。

狙いは、Jevのtoken消費を「毎秒」ではなく「1ラウンドごと」にすることです。

## 勝負幅

Fifty+ は利確と損切りを同じ幅にします。

### FX

UIでpipsを指定します。

例:

- 勝負幅: 5 pips
- LONGならネット損益 +5 pips相当で利確、-5 pips相当で損切り
- SHORTは逆方向

### BTC/JPY

pipsではなく円損益を指定します。

例:

- 勝負額: 500円
- ネット損益 +500円で利確、-500円で損切り

判定はspread、fee、slippageを含むネット損益ベースです。単純な価格差だけで1:1に見せるのではなく、実際のpaper PnLで対称になるようにします。

## ラウンド

通常の流れは次です。

```text
FLAT
  ↓
Jev: UP / DOWN
  ↓
LONG または SHORT を1つOPEN
  ↓
Jevは休止
  ↓
+X または -X のネット損益へ到達
  ↓
CLOSE
  ↓
次のJev判断
```

live paperでは、Jev回答時に直近quoteがfreshならそのquoteでpaper entryします。quoteが古い場合は価格を捏造せず、次のfresh tickを待って改めて次ラウンドを始めます。

## 何を測るか

Fifty+で重要なのは総損益だけではありません。

最低限、次を観察します。

- ラウンド数
- UP / DOWNの選択回数
- 勝数 / 負数
- 方向判定勝率
- net PnL
- spread / fee / slippage
- Profit Factor
- max drawdown
- 1ラウンドあたりJev input/output tokens
- 1ラウンドあたりAPI cost
- 平均保有時間
- TP / SL到達までのtick数

最初の主問いは「Jevの二択判断は、コスト込みでも50%を継続的に超えられるか」です。

## R Editionについて

過去の個人検証では、Fifty+ に追加フィルタを加えた "Fifty+mini R Edition" も試しています。

当時の主な要素:

- 5分足
- +DI / -DI による方向判定
- ADX 25〜40
- 直前ローソク足フィルタ
- 経済イベント回避
- TP / SL ±5 pips
- spread上限
- 3連敗で停止
- 東京時間中心

JevPipの初期Fifty+には、これらをまだ入れません。まず原型のUP / DOWN二択だけを検証し、その後必要ならR Edition相当を比較モードとして追加します。

## 境界

Fifty+ はpaper research用です。

- 実注文は行いません。
- BTC SHORTはsynthetic shortです。
- 板の深さ、部分約定、動的slippage等は完全には再現しません。
- 結果は将来の収益性を保証しません。
