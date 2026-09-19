from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import threading
import webbrowser

from jevpip.backtest.kline import replay_kline
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
    parser = argparse.ArgumentParser(prog="jevpip", description="JevPip USD/JPY 研究アプリ")
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

    obs = sub.add_parser("observe", help="GMOのUSD/JPYを観測してraw tickを保存")
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

    bt = sub.add_parser("backtest", help="GMO公式1分足を使う粗い履歴リプレイ")
    bt.add_argument("--date", required=True, help="YYYYMMDD (GMO FX KLine availabilityに従う)")
    bt.add_argument("--profile", default="technical")
    bt.add_argument("--feature-config", type=Path)
    bt.add_argument("--limit", type=int)
    bt.add_argument("--output", type=Path)

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

        print(f"profile={args.profile}: {profile.get('description_ja', '')}")
        print("接続先: GMO 外国為替FX Public WebSocket / USD_JPY")
        asyncio.run(
            observe(
                profile,
                settings.data_dir,
                jev,
                args.jev_every,
                args.max_ticks,
                signal_policy,
                args.signal_policy if signal_policy else None,
            )
        )
        return 0

    if args.command == "backtest":
        profile = load_profile(args.profile, args.feature_config)
        output = args.output or settings.data_dir / "backtests" / f"{args.date}-{args.profile}.jsonl"
        rows = replay_kline(args.date, profile, output=output, limit=args.limit)
        print(f"replayed={len(rows)} profile={args.profile}")
        print(f"saved={output}")
        print("注意: 1分足リプレイは5秒/30秒スキャルピング性能の検証には使えません。")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
