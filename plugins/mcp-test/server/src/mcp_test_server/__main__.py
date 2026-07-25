"""CLI 진입점."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import sys

from .app import DEFAULTS, PortInUse, _utcnow, serve
from .logpaths import resolve_log_dir
from .logsetup import configure_logging
from .logstream import LogBroadcaster


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
    parser.add_argument(
        "--log-dir",
        default=None,
        help=(
            "로그 파일을 남길 디렉토리. 지정하지 않으면 $MCP_TEST_LOG_DIR, "
            "그다음 플러그인 설정, 그다음 ~/.mcp-test-server/logs 를 쓴다"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    log_dir, warnings = resolve_log_dir(
        flag=args.log_dir, env=os.environ.get("MCP_TEST_LOG_DIR")
    )
    handle = configure_logging(
        log_dir=log_dir,
        port=args.port,
        clock=_utcnow,
        broadcaster=LogBroadcaster(),
    )
    # 로깅이 준비된 뒤에 남긴다. 경로를 정하는 동안에는 남길 곳이 없었다.
    for message in warnings:
        logging.getLogger("mcp_test_server.app").warning("%s", message)
    atexit.register(logging.shutdown)

    try:
        asyncio.run(
            serve(
                host=args.host,
                port=args.port,
                admin_port=args.admin_port,
                stale_after=args.stale_after,
                handle=handle,
            )
        )
    except PortInUse as exc:
        print(f"기동 실패: {exc}", file=sys.stderr)
        print("--port 또는 --admin-port 로 다른 포트를 지정하라.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except BaseException:
        # Exception 이 아니라 BaseException 이다. uvicorn 은 바인딩에 실패하면
        # sys.exit(1) 을 부르고 SystemExit 은 BaseException 이다 —
        # app.py 의 ensure_port_free 주석이 그 사실을 기록하고 있다.
        logging.getLogger("mcp_test_server.app").exception("처리되지 않은 예외로 종료한다")
        raise
    finally:
        # atexit 은 인터프리터가 정리를 시작한 뒤에 돈다. 그때 파일 핸들러가
        # 부르는 시계는 모듈 전역을 참조하므로 이미 사라졌을 수 있다.
        # 여기서 명시적으로 비우는 것이 주 경로다.
        logging.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
