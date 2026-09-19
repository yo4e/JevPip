# External Context Research for Jev Supervisor

更新日: 2026-09-19

Issue #4 Phase 3 のための調査メモ。

## 結論

最初の external context は、広いニュース scraping ではなく **official-source-first の scheduled event metadata** から始める。

理由:

- 発表予定時刻を事前に扱える
- provenance を明示しやすい
- historical / paper 比較で look-ahead を制御しやすい
- headline や本文の再利用条件を抱え込みにくい
- latency-sensitive なニュース配信を自前で再現しなくてよい
- deterministic supervisor の event pause baseline を先に作れる

Jevへ渡す情報も、当面は本文ではなく「何が、いつ、どの公式sourceから、どの通貨/銘柄に関係するか」を中心にする。

## 最初に使うsource候補

### 1. Bank of Japan

Official:

- Monetary Policy Meetings:
  https://www.boj.or.jp/en/mopo/mpmsche_minu/
- Release Schedule:
  https://www.boj.or.jp/en/about/calendar/index.htm
- Copyright / reuse:
  https://www.boj.or.jp/en/about/copyright.htm

使い道:

- Monetary Policy Meeting
- Outlook Report
- Summary of Opinions
- Minutes
- その他の予定公表

重要な境界:

日銀サイトは転載条件が比較的厳しい。source attributionが必要で、commercial-purpose reproduction等には事前許可が必要となる条件がある。

したがってJevPipでは、公開repoへ本文・大量のコピー・固定calendar dumpを保存しない。

保持するのは原則:

- source id
- title
- scheduled timestamp
- observed timestamp
- source URL
- local tags

実際の取得結果はruntime dataとして扱い、Gitへcommitしない。

### 2. Federal Reserve Board

Official:

- FOMC calendars:
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Disclaimer / copyright:
  https://www.federalreserve.gov/disclaimer.htm

FOMC calendarはmeeting dates、statement、minutes、press conference、projection materials等を整理している。

Federal Reserve Boardサイトの情報は、別途表示がない限りpublic domainとしてcopy/distribute可能。source citationは行う。

最初の用途:

- FOMC meeting / statement window
- minutes release window
- projection release window

### 3. U.S. Bureau of Labor Statistics

Official:

- release schedule:
  https://www.bls.gov/schedule/
- calendar subscription:
  https://www.bls.gov/schedule/news_release/bls.ics
- copyright:
  https://www.bls.gov/opub/copyright-information.htm
- API terms:
  https://www.bls.gov/developers/termsOfService.htm

BLSはCPI、Employment Situation、PPI、JOLTS等の予定を公開し、公式ICS calendarも提供している。

BLS公開物は、明示的な例外を除きpublic domain。

v0では少なくとも:

- Consumer Price Index
- Employment Situation
- Producer Price Index

を high-risk scheduled event として扱う候補。

### 4. ECB / other central banks

EUR/JPY等へ広げるときの候補。

ECB official meeting calendar:
https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html

ECB website reuse:
https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html

ECBはsource表記等の条件つきでwebsite informationのfree useを認めている。

他の対円pairについても、各中央銀行のofficial calendarを優先する。

例:

- Bank of England
- Reserve Bank of Australia
- Reserve Bank of New Zealand
- Bank of Canada
- Swiss National Bank
- CBRT
- SARB
- Banco de México
- Magyar Nemzeti Bank
- Sveriges Riksbank

ただし最初から12通貨分を同時実装しない。
USD/JPY + BTC/JPYのpaper experimentでpipelineを固めてからadapterを増やす。

## Crypto-specific context

BTC固有ニュースを最初から広く収集しない。

crypto newsは:

- source品質差
- 著作権 / redistribution
- duplicate
- headline rewriting
- rumor
- latency

が一気に増える。

v0ではBTCもUSD macro event contextの影響を見る。
crypto固有sourceは、official / attributable sourceを個別に選定して後段で追加する。

候補カテゴリ:

- exchange maintenance / incident
- regulator official releases
- protocol/client official releases

「重要そうなcrypto newsを全部拾う」aggregatorは初期scope外。

## Source model

external context itemは最低限:

- source
- source_id
- kind
- title
- source_url
- observed_at
- scheduled_at or published_at
- expires_at
- currencies
- instruments
- local risk tag

を持つ。

raw article body / arbitrary HTML はcore schemaへ入れない。

## Timestamp semantics

最重要。

### observed_at

JevPipがその情報を初めて観測した時刻。

### scheduled_at

予定イベントの発生/公開予定時刻。

### published_at

実際に公開されたコンテンツの時刻。

### as_of

paper / replay decisionの時刻。

contextは、必ず:

- observed_at <= as_of
- published_atがある場合 published_at <= as_of

のものだけ使う。

これにより、あとから更新されたcalendarやreleaseを過去のdecisionへ逆流させない。

## Calendar revision

official calendarは変更されうる。

同じ source + source_id が後から更新された場合:

- revisionを上書きして歴史を書き換えない
- observed_at付きで保持
- decision時点で既知だった最新revisionだけを選ぶ

historical experimentで「現在の最新calendarを過去へ当てはめる」ことは禁止。

## Dedup

第一キー:

- source
- source_id

fallbackが必要なsourceだけ:

- normalized title
- scheduled/published timestamp
- source URL

からstable hashを作る。

異なるofficial sourceの同一イベントは、source provenanceを失わないため無理に1件へ潰さない。

## Local risk classification

sourceが公式にimportanceを提供していない場合、importanceをsource factのように保存しない。

JevPip側のruleとして:

- critical
- high
- medium
- low

を付ける場合は **local classification** として扱う。

初期例:

critical/high候補:

- central bank policy decision
- CPI
- Employment Situation

これは「市場への影響を保証するラベル」ではなく、event-window supervision用のlocal rule。

## Deterministic baseline first

Jevより先に scheduled event deterministic supervisor を作る。

例:

- high/critical eventの前30分〜後15分: PAUSE_ENTRY
- medium: CAUTION
- calendar fetch stale / unavailable: 既存market safetyを緩めない

event ruleはJevなしで動く。

その上でJevに同じevent metadataを渡し、追加価値があるか比較する。

## Jev state boundary

Jevへ渡す候補:

```json
{
  "as_of": "2026-09-19T03:30:00+00:00",
  "external_context": [
    {
      "kind": "scheduled_event",
      "source": "bls",
      "source_id": "cpi-2026-09",
      "title": "Consumer Price Index",
      "risk": "high",
      "currencies": ["USD"],
      "instruments": [],
      "event_at": "2026-09-19T04:00:00+00:00",
      "seconds_from_now": 1800,
      "observed_at": "2026-09-18T00:00:00+00:00"
    }
  ]
}
```

入れない:

- API key
- browser secret
- arbitrary HTML
- unbounded article body
- future release value
- after-the-fact revised calendar
- order quantity / TP / SL / leverage

## A/B/C/D experiment design

同じmarket path、strategy settings、cost modelを使う。

A. technical only

- code strategy
- market status/spread/stale等の既存safetyは最低限維持
- external event supervisorなし

B. technical + deterministic event supervisor

- official scheduled event metadata
- code-only pause/caution rule

C. technical + deterministic + Jev supervisor

- Bと同じcontext
- bounded Jev adviceを追加
- deterministic safetyをJevは解除できない

D. Jev direct signal

- 既存research control
- supervisor方式との比較用
- mainline designにはしない

### 比較指標

既存:

- net PnL
- Profit Factor
- max DD
- win rate
- trade count
- fee
- average trade / win / loss

追加:

- pause duration
- blocked entry count
- Jev-only tightened decisions
- avoided loss
- missed profit
- false pause
- strategy switch count
- context unavailable count

## Counterfactual logging

「Jevが止めて損失を避けた」を測るには、実際に止めたtradeを単に消すだけでは足りない。

experiment harnessでは、blocked candidate entryについて:

- original strategy signal
- decision time
- supervisor reason
- context ids
- 仮にentryしていた場合の同一cost modelでのcounterfactual result

を別streamで計算する。

これで:

- avoided loss
- missed profit

を同じ定義で比較できる。

## Public repository boundary

public repoへcommitしてよい:

- source adapter code
- schema
- parser
- fixturesとして自作したsynthetic data
- source URLs
- design / research notes

原則commitしない:

- TypeSafe/Jev performance実測
- third-party article bodies
- runtime fetched calendar dumps
- credentials
- private account data

## 実装順序

1. provenance-first context schema
2. look-ahead-safe selection
3. BLS ICS adapter
4. Fed / BOJ scheduled-event adapter
5. deterministic event-window supervisor
6. runtime context log
7. paper-only Jev supervisor call
8. A/B/C/D experiment harness
9. official post-release text/headlineは必要性を確認してから追加

広いニュースfeedはこの後。
