from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import threading
import webbrowser

from jevpip.backtest.kline import replay_kline
from jevpip.broker.comparison import compare_raw_file
from jevpip.instruments import INSTRUMENTS, get_instrument
from jevpip.config import (
    Settings,
    list_profiles,
    list_signal_policies,
    load_profile,
    load_signal_policy,
)
from jevpip.observer import observe
from jevpip.signals import SignalPolicy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevpip", description="JevPip ローカル市場研究ターミナル")
    sub = parser.add_subparsers(dest="command", required=True)

    ui = sub.add_parser("ui", help="日本語のローカルWeb UIを起動")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")

    features = sub.add_parser("features", help="特徴量プロファイル")
    features.add_argument("action", choices=["list"])
    features.add_argument("--config", type=Path)

    signals = sub.add_parser("signals", help="研究用売買シグナル設定")
    signals.add_argument("action", choices=["list"])
    signals.add_argument("--config", type=Path)

    obs = sub.add_parser("observe", help="GMO marketを観測してraw tickを保存")
    obs.add_argument("--instrument", default="USD_JPY", choices=sorted(INSTRUMENTS))
    obs.add_argument("--profile", default="minimal")
    obs.add_argument("--feature-config", type=Path)
    obs.add_argument("--signal-policy", default="research_default")
    obs.add_argument("--signal-config", type=Path)
    obs.add_argument(
        "--with-jev",
        action="store_true",
        help="TypeSafe Jevも呼ぶ（API利用料金が発生し得ます）",
    )
    obs.add_argument("--jev-every", type=float, default=1.0, metavar="SECONDS")
    obs.add_argument("--max-ticks", type=int)

    bt = sub.add_parser("backtest", help="対円FXのGMO公式BID/ASK 1分足リプレイ")
    bt.add_argument("--instrument", default="USD_JPY", choices=sorted(INSTRUMENTS))
    bt.add_argument("--date", required=True, help="YYYYMMDD (GMO FX KLine availabilityに従う)")
    bt.add_argument("--profile", default="technical")
    bt.add_argument("--feature-config", type=Path)
    bt.add_argument("--limit", type=int)
    bt.add_argument("--output", type=Path)

    cmp = sub.add_parser("compare", help="保存済みraw tickでcode-only paper strategyを比較")
    cmp.add_argument("--instrument", required=True, choices=sorted(INSTRUMENTS))
    cmp.add_argument("--file", required=True, type=Path, help="raw tick JSONL")
    cmp.add_argument("--strategies", default="momentum,rsi_mean_reversion,ma_trend")
    cmp.add_argument("--initial-balance", type=float, default=100000.0)
    cmp.add_argument("--size", type=float)
    cmp.add_argument("--no-supervisor", action="store_true")
    cmp.add_argument("--bar-seconds", type=int, choices=[0, 5, 15, 60, 300], default=0, help="RSI/MA入力: 0=tick, または確定bar秒数")
    cmp.add_argument("--json", action="store_true", help="JSONで出力")
    return parser


def _run_ui(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{port}"
    print(f"JevPip UI: {url}")
    print("終了するにはターミナルで Ctrl+C を押してください。")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run("jevpip.web.app:app", host=host, port=port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()

    if args.command == "ui":
        return _run_ui(args.host, args.port, not args.no_open)

    if args.command == "features":
        for name, profile in sorted(list_profiles(args.config).items()):
            print(f"{name:16} {profile.get('description_ja', '')}")
        return 0

    if args.command == "signals":
        for name, policy in sorted(list_signal_policies(args.config).items()):
            print(f"{name:16} {policy.get('description_ja', '')}")
        return 0

    if args.command == "observe":
        profile = load_profile(args.profile, args.feature_config)
        jev = None
        signal_policy = None
        if args.with_jev:
            if not settings.typesafe_api_key:
                raise SystemExit("--with-jev には TYPESAFE_API_KEY が必要です")
            from jevpip.jev.client import JevClient

            jev = JevClient(settings.typesafe_api_key)
            raw_policy, description = load_signal_policy(args.signal_policy, args.signal_config)
            signal_policy = SignalPolicy.from_dict(raw_policy)
            print(f"signal={args.signal_policy}: {description}")

        instrument = get_instrument(args.instrument)
        print(f"profile={args.profile}: {profile.get('description_ja', '')}")
        print(f"instrument={instrument.display_symbol} market={instrument.market_kind}")
        asyncio.run(
            observe(
                profile,
                settings.data_dir,
                jev,
                args.jev_every,
                args.max_ticks,
                signal_policy,
                args.signal_policy if signal_policy else None,
                instrument_id=args.instrument,
            )
        )
        return 0

    if args.command == "backtest":
        instrument = get_instrument(args.instrument)
        if instrument.market_kind != "fx" or instrument.quote_currency != "JPY":
            raise SystemExit("backtest は現在、対円FXペアのみ対応しています")
        profile = load_profile(args.profile, args.feature_config)
        output = args.output or settings.data_dir / "backtests" / f"{args.date}-{args.instrument}-{args.profile}.jsonl"
        rows = replay_kline(
            args.date,
            profile,
            output=output,
            limit=args.limit,
            instrument_id=args.instrument,
        )
        print(f"replayed={len(rows)} instrument={instrument.display_symbol} profile={args.profile}")
        print(f"saved={output}")
        print("注意: 1分足リプレイは5秒/30秒スキャルピング性能の検証には使えません。")
        return 0

    if args.command == "compare":
        strategies = tuple(x.strip() for x in args.strategies.split(",") if x.strip())
        allowed = {"momentum", "rsi_mean_reversion", "ma_trend"}
        unknown = sorted(set(strategies) - allowed)
        if unknown:
            raise SystemExit(f"compare未対応strategy: {', '.join(unknown)}")
        results = compare_raw_file(
            args.file,
            instrument_id=args.instrument,
            strategies=strategies,
            initial_balance=args.initial_balance,
            size=args.size,
            supervisor=not args.no_supervisor,
            bar_seconds=args.bar_seconds,
        )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0

        mode = "tick" if args.bar_seconds == 0 else f"{args.bar_seconds}s bars"
        print(f"file={args.file} instrument={get_instrument(args.instrument).display_symbol} strategy_input={mode}")
        print("strategy              net_pnl       PF     maxDD   trades    win%      fees")
        for name, row in results.items():
            pf = "-" if row["profit_factor"] is None else f'{row["profit_factor"]:.2f}'
            win = "-" if row["win_rate"] is None else f'{row["win_rate"] * 100:.1f}'
            print(
                f"{name:20} {row['net_pnl']:>9.1f} {pf:>8} "
                f"{row['max_drawdown']:>9.1f} {row['closed_trades']:>8} "
                f"{win:>7} {row['fees_paid']:>9.1f}"
            )
        print("注意: 同じraw tickと同じpaper cost modelでの比較です。将来利益を示すものではありません。")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
