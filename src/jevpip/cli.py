from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from jevpip.backtest.kline import replay_kline
from jevpip.config import Settings, list_profiles, load_profile
from jevpip.observer import observe


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevpip", description="JevPip USD/JPY research lab")
    sub = parser.add_subparsers(dest="command", required=True)

    features = sub.add_parser("features", help="特徴量プロファイル")
    features.add_argument("action", choices=["list"])

    obs = sub.add_parser("observe", help="GMOのUSD/JPYを観測してraw tickを保存")
    obs.add_argument("--profile", default="minimal")
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
    bt.add_argument("--limit", type=int)
    bt.add_argument("--output", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()

    if args.command == "features":
        for name, profile in sorted(list_profiles().items()):
            print(f"{name:16} {profile.get('description_ja', '')}")
        return 0

    profile = load_profile(args.profile)

    if args.command == "observe":
        jev = None
        if args.with_jev:
            if not settings.typesafe_api_key:
                raise SystemExit("--with-jev には TYPESAFE_API_KEY が必要です")
            from jevpip.jev.client import JevClient

            jev = JevClient(settings.typesafe_api_key)

        print(f"profile={args.profile}: {profile.get('description_ja', '')}")
        print("Connected target: GMO FX Public WebSocket / USD_JPY")
        asyncio.run(
            observe(
                profile,
                settings.data_dir,
                jev,
                args.jev_every,
                args.max_ticks,
            )
        )
        return 0

    if args.command == "backtest":
        output = args.output or settings.data_dir / "backtests" / f"{args.date}-{args.profile}.jsonl"
        rows = replay_kline(args.date, profile, output=output, limit=args.limit)
        print(f"replayed={len(rows)} profile={args.profile}")
        print(f"saved={output}")
        print("注意: 1分足リプレイは5秒/30秒スキャルピング性能の検証には使えません。")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
