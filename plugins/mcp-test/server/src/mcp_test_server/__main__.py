"""CLI 진입점."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .app import DEFAULTS, PortInUse, serve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp-test-server",
        description="여러 Claude Code 세션이 공유하는 MCP 테스트 서버",
    )
    parser.add_argument(
        "--host",
        default=DEFAULTS["host"],
        help=(
            "MCP 리스너 바인딩 주소. 루프백 밖(예: 0.0.0.0)에 열면 인증이 "
            "비어 있지 않은 토큰을 전부 통과시키므로, 그 포트에 닿는 사람은 "
            "누구나 모든 세션의 프로젝트 경로와 토큰을 읽을 수 있다"
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULTS["port"], help="MCP 리스너 포트")
    parser.add_argument(
        "--admin-port",
        type=int,
        default=DEFAULTS["admin_port"],
        help="관리 리스너 포트 (주소는 127.0.0.1 고정)",
    )
    parser.add_argument(
        "--stale-after",
        type=float,
        default=DEFAULTS["stale_after"],
        help="이 시간(초) 동안 호출이 없으면 stale로 표시한다",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(
            serve(
                host=args.host,
                port=args.port,
                admin_port=args.admin_port,
                stale_after=args.stale_after,
            )
        )
    except PortInUse as exc:
        print(f"기동 실패: {exc}", file=sys.stderr)
        print("--port 또는 --admin-port 로 다른 포트를 지정하라.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
