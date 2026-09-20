# Jevおまかせ（paper prototype）

Issue #17 の試作実装。Jevが保有方向と**目標総数量**を選び、brokerが現在数量との差分だけを約定する。live paperと保存済みraw tickのJev BTで同じ質問・validator・brokerを使う。実注文機能は追加していない。

## 始め方

1. デモ自動売買で「Jevおまかせ」をON（UI初期値）。TypeSafe APIキーを設定する。
2. 銘柄、基準数量、仮想残高、Jevおまかせスタイルを選ぶ。**デイトレ**は1分足中心・標準300秒間隔・10分horizon、**スキャルピング**は直近tick中心・標準1秒間隔・30秒horizon。**Fifty+**は常に1ポジションを持ち、決済時だけJevへ次のUP / DOWNを二択で問い合わせる。FXはpips、BTCは円で対称のネット利確・損切り幅を指定する。
3. 「公式イベントを見る」を使う場合はチェックする。現在は観測済みのBLS / BOJ / Fed等の公式イベント予定だけを渡す。広義のニュース・指標実績・市場解説をまとめて取得する機能ではない。
4. 必要な制約だけ「Jevを縛る・詳細設定」でチェックし、開始する。

判断間隔と見通す時間は別。見通す時間は30秒・2分・10分・30分から選ぶ。デイトレの初期値は10分、スキャルピングは30秒。これらは最適化済みの推奨値でも強制決済時刻でもない。従来の固定TP/SL・最大8秒保有・コード戦略・supervisorはこのモードには適用しない。

### デイトレ / スキャルピング / Fifty+

- `daytrade`: 現行Jevおまかせのrolling market historyを維持し、最大30本の確定1分足を渡す。標準cadenceは300秒。
- `scalp`: 直近40 tickの時刻・MID・spread・前tick比を `autopilot.recent_ticks` として渡し、確定1分足は最大5本に絞る。標準cadenceは1秒。
- `fifty`: FLAT / KEEPをモデル候補に出さず、`UP / DOWN` の二択だけを渡す。UPは基準数量のLONG、DOWNは基準数量のSHORT。ポジション保有中はJev APIを呼ばず、対称のTP/SLで決済された後にだけ次の方向判断を要求する。
  - 背景にある実験仮説と設計思想は [FIFTY_PLUS.md](./FIFTY_PLUS.md) を参照。
- Fifty+のFX勝負幅は `autopilot_fifty_target_units`、BTCは `autopilot_fifty_target_jpy`。判定はspread・手数料・slippage込みのネット損益で +X / -X とする。
- Fifty+では方向選択に不要なaccount / cost / constraints / recent executionをJev stateから外し、直近tickと短い価格履歴を中心に渡す。コストを理由に棄権する選択肢はない。
- デイトレとスキャは同じtarget-position broker、口座会計、cost model、optional risk constraintsを使う。スキャでも売買回数を強制せず、往復コストを上回る短期edgeが見込めない場合はFLAT/KEEPを許す。

おまかせOFFで従来の方向判定・Momentum / RSI / MA・supervisorを使える。既存APIの `autopilot_enabled` は省略時OFF。Strategy BT、raw comparison、A/B/C/D harnessは従来モードの比較用として残る。

## モデルとコードの契約

JevはTypeSafeの独立した2つのChoice質問に答える。

- `target_position`: KEEP / FLAT / LONGまたはSHORTのSMALL・BASE・LARGE。数量は基準の0.5・1・2倍を数量刻みに切り捨てる。新規・増額で資金上限、最大数量、最大保有額を超える候補は渡さない。
- `decision_factor`: NO_EDGE / COST_TOO_HIGH / TREND / REVERSAL / REDUCE_RISK / KEEP_THESIS。target_positionとは独立したChoiceで、売買判断の因果的な「理由」を保証するものではない。現在stateで目立つ判断要因の分類として記録する。

KEEPは現在数量、FLATは0。LONG 1000→LONG 1000は約定なし、LONG 1000→LONG 500は500減額、LONG 1000→SHORT 1000は全決済と新規SHORTを同一decision IDへ紐付ける。BTCは0.0001 BTC、FXは1通貨刻み。任意数量・任意コマンドをモデルから受け取る構造ではない。

コードが `schema_version / decision_id / session_id / account_version / instrument_id / target_side / target_quantity / confidence / reason / horizon_seconds / basis_market_timestamp / requested_at / available_at / expires_at` を組み立てる。選択肢、確率集合・合計、confidence、有限数、数量刻み、銘柄、時刻順を検証する。confidenceは実測勝率ではない。

stateは現在bid/ask、spread、残高/equity、確定/含み損益、positionの数量・平均建値・年齢、手数料/slippage、往復コスト・損益分岐の値幅、候補への移行費用、直近8約定、履歴長と最大tick間隔、選択したfeatures、任意の公式イベントcontextを含む。デイトレでは最大30本の確定1分足、スキャでは最大5本の確定1分足に加えて直近40 tickを渡す。起動直後の履歴不足や疎なtickを隠さない。APIキー・実口座情報は渡さない。

## 約定・会計

- bid/askと設定slippageで全量約定する近似。板の厚みや部分約定は再現しない。
- 増額は加重平均建値。減額は入口の手数料・slippage・spreadを数量比で配賦。
- 残高は確定純損益と未決済分の支払済み入口手数料を反映。equityは残高＋現在決済した場合の含み損益（推定出口手数料込み）。
- 決済損益は `midの値動き − spread − slippage − 往復手数料`。gross PnLにはspread/slippageが既に含まれるので再控除しない。
- `execution_fee` はその約定で支払った手数料。決済行の `fees / slippage_cost / spread_cost` は入口配賦分も含む。OPEN行との単純合計は二重計上になる。
- 部分決済も1決済として勝率・PF・平均損益を集計する。反転は2約定、目標変更は1回。KEEPや拒否は変更回数に含めない。
- 平均保有額は観測区間の時間加重絶対notional。tick間は直前のnotionalを据え置く。最大保有額・最大tick間隔も保存する。

新規・増額・反転のnotionalは、追加する往復費用を引いたequityの1倍以内。BTCのSHORTは仮想ショートであり、FXの実証拠金率も再現しない。既存保有が値動きで上限を超えても、この資金上限だけでは強制決済しない。

## 制約・失敗時の動作

任意制約は未チェックなら `null`。最大数量・保有額・DD金額/比率・1回の数量変更・新規停止損失・spread・confidence・cooldown・最大保有時間・TP/SLを個別に設定できる。

最大数量・保有額・spread・confidence・cooldown・新規停止損失は新規/増額/反転を制限する。最大数量変更は減額/FLATも含む。強制TP/SL・最大保有時間・DD停止はこれらの任意entry制約に優先して全決済する。TP/SLは数量あたりの**手数料控除後**損益を銘柄の値幅単位で評価する。DD到達・equity枯渇は決済後も停止を保持し、口座リセットで解除する。

以下は解除できない。

- paper only、不正応答の拒否、有限かつ非負の数量、数量刻み、資金上限。
- OPENかつ鮮度内の価格だけで約定。古いquote・閉場・無更新時に架空の約定を作らない。
- TTLは標準5秒（最大60秒）。参照quoteとrequestの早い方から起算し、遅い回答は破棄。
- 参照した口座version/sessionと現在値が一致すること。resetや別約定をまたぐ回答は破棄。
- 応答受信後の市場timestampを持つtickから約定。重複・逆順応答は適用しない。
- 増額・反転は標準2回連続一致（1〜5回で設定可能）。減額は待たない。同じ目標の再送では積み増さない。

APIエラーやmalformed responseでFLATを合成しない。保有は維持し、任意の強制exitはtickごとに評価する。requestは1本ずつで開始間隔がcadenceを下回らない。遅延分の追いつきcallはしない。おまかせのSDK timeoutは10秒、自動retryなし。停止時は進行中の同期API処理の終了を待ち、遅い結果を捨ててから再開を許可する。

## Historical Jev BT

右側の同じ設定をJev BTへ渡す。1/2/5/10/30/60秒間隔、30秒〜1日のwindow、token確認、10,000 calls上限を維持。previewの最大call数は実行時にも上限として適用する。observer/replayと新しい実行は重ねない。処理がcancelされた場合は進行中の1callを待ち、残りのcallを始めない。

受信時刻をrequest時刻とし、実測API latencyを加えて回答の利用可能時刻を求める。market/received timestampが因果順でないrawファイルは実APIを呼ぶ前に拒否する。window前のraw tickは過去チャートの準備だけに使用する。最終tickでは新規建玉を作らず、取引可能な価格なら残りを強制決済する。最終価格が古い/閉場なら保有を残した評価額となる。

ファンダONのhistorical replayは明示的に拒否する。現在のイベント情報を過去へ流用しない。liveの公式contextも、後日観測したrevisionを過去時点の判断に混ぜない。

`data/jev_replays/<instrument>/` に設定、raw source path/window、全request state、モデル応答・usage・実測latency、判断trace、全約定、集計をJSONLで保存する。画面は直近100約定。liveは既存 `decisions/` と `decision_traces/` に保存し、反転の両約定もtraceに残す。

## 検証と残る課題

unit testsは模擬応答だけで会計、独立cash ledgerとの照合、部分決済/反転、schema、pending/TTL、同時開始、停止、replay、fundamentalsを検証する。有料Jev replayや収益性の検証は実施していない。

収益性を調べる際は、短い接続確認の後、別日・別区間を残して比較する。従来Jev、code-only、No Tradeも同条件で残し、net PnL / PF / DDだけでなく手数料、売買総額、保有額、変更回数、calls / tokens / API費用、tickの欠落を見る。疎なraw tickでは1秒判断・約定を検証できない。

暫定部分は固定数量候補と見通し候補、current `jev-latest`、単純全量約定、historical fundamentals未対応、比較runの手動実行。保存ログは現行モデルの再問い合わせ結果であり、過去モデルの再現でも完全再現可能なbenchmarkでもない。raw source fileやAPI modelは固定・同梱していない。実測performanceや取引ログをpublic repositoryへcommitしない方針を維持する。
