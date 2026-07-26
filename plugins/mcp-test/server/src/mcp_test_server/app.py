"""두 ASGI 앱을 조립하고 한 프로세스에서 함께 기동한다.

## 응용할 때

**바꿔도 되는 것.** `DEFAULTS` 의 포트와 유휴 기준, 그리고
`build_stack()` 이 무엇을 무엇으로 감싸는지. 미들웨어를 더한다면 거기다.

**깨면 안 되는 것.**

- `AccessLogMiddleware` 가 `AuthMiddleware` **바깥**이어야 한다. 안으로
  넣으면 401/403 으로 거부된 요청이 로그에 남지 않는다 — 이 서버에서
  가장 보고 싶은 줄이 그것이다.
- 관리 리스너의 주소는 `ADMIN_HOST` 고정이다. 인증이 없는 리스너이므로
  바꿀 수 있는 통로를 만들지 않는다.
- `uvicorn.error` 레벨을 되돌리는 줄은 `build_servers()` 뒤여야 한다.
  이유는 그 줄의 주석에 있다.
- 두 리스너는 같은 이벤트 루프를 공유한다. 이것이 `registry` 의 락 없는
  설계가 성립하는 근거다. 별도 프로세스나 스레드로 쪼개려면 거기부터
  다시 봐야 한다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from starlette.types import ASGIApp

from .access import AccessLogMiddleware
from .admin import build_admin_app
from .auth import AuthMiddleware
from .logpaths import MAX_AGE_SECONDS, purge_logs
from .logsetup import LoggingHandle
from .logstream import LogBroadcaster
from .mcp_server import build_mcp
from .registry import Registry

logger = logging.getLogger("mcp_test_server.app")
registry_logger = logging.getLogger("mcp_test_server.registry")

# 관리 리스너는 루프백에 고정한다. 인증이 없는 리스너이므로 이 값을
# 바꿀 수 있는 통로를 만들지 않는다.
ADMIN_HOST = "127.0.0.1"

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8765,
    "admin_port": 8766,
    "stale_after": 300.0,
}

_PURGE_INTERVAL_SECONDS = 600.0

# 종료 신호를 받고 열린 연결이 닫히기를 기다리는 한도(초). build_servers 참조.
_GRACEFUL_SHUTDOWN_SECONDS = 3

# "모든 인터페이스"를 뜻하는 주소들. 접속 대상 주소가 아니다.
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})


def is_loopback(host: str) -> bool:
    """이 주소가 이 기계 밖에서 닿지 않는 주소인지 판단한다."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def endpoint_host(host: str) -> str:
    """바인딩 주소를 클라이언트가 실제로 접속할 수 있는 주소로 바꾼다.

    0.0.0.0 과 :: 는 "모든 인터페이스에 바인딩하라"는 지시이지 접속 대상
    주소가 아니다. 그대로 URL에 넣으면 받는 쪽이 쓸 수 없다.
    """
    return "127.0.0.1" if host in _WILDCARD_HOSTS else host


def exposure_warning(host: str) -> str | None:
    """루프백 밖에 노출될 때 보여줄 경고문. 안전하면 None.

    serve() 안에 인라인으로 두면 경고 여부를 판단하는 규칙을 테스트가
    확인할 수 없다. 아무것도 출력하지 않는 순수 함수로 떼어 둔다.
    """
    if is_loopback(host):
        return None
    return (
        f"경고: {host} 는 루프백 주소가 아니다. 이 서버의 인증은 비어 있지 않은 "
        "Bearer 토큰이면 무엇이든 통과시키므로, 이 포트에 닿을 수 있는 사람은 "
        "누구나 연결된 모든 세션의 프로젝트 경로와 토큰을 읽고 세션을 지울 수 "
        "있다. 신뢰할 수 없는 망에서는 쓰지 마라."
    )


class PortInUse(OSError):
    """기동 전 포트 확인에서 이미 사용 중임을 발견했을 때."""


def ensure_port_free(host: str, port: int) -> None:
    """포트를 쓸 수 있는지 미리 확인한다.

    uvicorn은 바인딩에 실패하면 sys.exit(1)을 호출한다. SystemExit은
    BaseException이라 except OSError로 잡히지 않고 우리 안내 메시지도
    출력되지 않는다. 기동 전에 직접 확인해 메시지를 통제한다.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise PortInUse(f"{host}:{port} 이(가) 이미 사용 중이다") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_stack(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    clock: Callable[[], datetime] = _utcnow,
    broadcaster: LogBroadcaster | None = None,
    log_file: Callable[[], Path | None] = lambda: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> tuple[ASGIApp, ASGIApp, Registry]:
    """MCP 앱, 관리 앱, 그리고 둘이 공유하는 레지스트리를 만든다.

    admin_port는 지금 쓰지 않는다. 나중에 관리 앱 쪽에 인증이나 Origin
    검사를 붙일 때 자기 포트를 알아야 하므로 자리를 비워 둔다.

    두 앱 모두 AccessLogMiddleware 로 감싼다. 관리 앱만 빼면 접근 로그가
    반쪽이 되고, uvicorn 의 access log 를 껐으므로 그쪽 요청은 어디에도
    남지 않는다.
    """
    started_at = clock()
    registry = Registry(stale_after=stale_after)

    mcp = build_mcp(registry, started_at=started_at, clock=clock)
    mcp_app = AccessLogMiddleware(
        AuthMiddleware(mcp.streamable_http_app(), registry=registry, clock=clock)
    )

    admin_app = AccessLogMiddleware(
        build_admin_app(
            registry,
            started_at=started_at,
            clock=clock,
            mcp_endpoint=f"http://{endpoint_host(host)}:{port}/mcp",
            broadcaster=broadcaster,
            log_file=log_file,
            should_stop=should_stop,
        )
    )
    return mcp_app, admin_app, registry


def build_servers(
    mcp_app: ASGIApp,
    admin_app: ASGIApp,
    *,
    host: str,
    port: int,
    admin_port: int,
) -> tuple[uvicorn.Server, uvicorn.Server]:
    """두 리스너의 uvicorn 설정을 만든다. 아직 아무것도 바인딩하지 않는다.

    serve() 안에 인라인으로 두면 "관리 리스너만은 ADMIN_HOST에 고정된다"는
    성질을 테스트가 확인할 방법이 없다. 바인딩 없이 설정만 돌려주는 함수로
    떼어 내 그 성질을 검증 가능하게 만든다.

    log_config=None 은 uvicorn 이 자기 핸들러를 설치하지 못하게 한다. uvicorn.error
    로거는 handlers=0, propagate=True 를 유지하므로 루트로 전파되어 우리 파일에
    잡힌다. 다만 Config 생성자가 그때마다 이 로거의 레벨을 자기 log_level 로 다시
    맞추고, 나중에 만든 관리 쪽(warning)이 이긴다 — 그래서 serve() 가 이 함수를
    부른 **직후에** uvicorn.error 의 레벨을 INFO 로 되돌린다. 그쪽에 설명이 있다.
    access_log=False 인 이유는 AccessLogMiddleware 가 양쪽 앱에 대해 같은 형식으로
    남기기 때문이다.

    timeout_graceful_shutdown 은 양쪽 모두에 준다. 이 서버는 장수 연결을 다룬다 —
    관리 앱의 /api/logs/stream 은 SSE 라 브라우저 탭이 열려 있는 한 끝나지 않고,
    MCP 쪽 streamable-http 도 알림용 GET 스트림을 붙들고 있다. 이 값이 없으면
    uvicorn 은 그 연결들이 스스로 닫히기를 무한정 기다리므로, 관리 화면을 열어 둔
    채 Ctrl-C 를 누르면 프로세스가 영영 끝나지 않는다. 3초는 진행 중인 짧은 요청이
    응답을 마치기에는 넉넉하고, 사람이 종료를 기다리기에는 짧은 값이다.
    """
    mcp_server = uvicorn.Server(
        uvicorn.Config(
            mcp_app,
            host=host,
            port=port,
            log_level="info",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
        )
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin_app,
            host=ADMIN_HOST,
            port=admin_port,
            log_level="warning",
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
        )
    )
    return mcp_server, admin_server


async def _purge_loop(
    registry: Registry,
    clock: Callable[[], datetime],
    log_dir: Path | None,
    log_file: Callable[[], Path | None],
    max_age_seconds: float,
) -> None:
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        now = clock()
        purged = registry.purge(now)
        if purged:
            registry_logger.info("오래된 세션 %d개를 정리했다", purged)
        if log_dir is not None:
            removed, warnings = purge_logs(
                log_dir, now, keep=log_file(), max_age_seconds=max_age_seconds
            )
            if removed:
                logger.info("오래된 로그 %d개를 지웠다", removed)
            for warning in warnings:
                logger.warning("%s", warning)


def _loop_exception_handler(
    loop: asyncio.AbstractEventLoop, context: dict[str, object]
) -> None:
    """태스크 안에서 난 예외는 main() 까지 오지 않는다.

    purge 태스크와 uvicorn 의 커넥션별 태스크가 여기 걸린다. 이걸 걸지
    않으면 그 예외들은 asyncio 의 기본 핸들러가 stderr 로만 흘려보내고,
    stderr 는 아무 데도 가지 않는다.
    """
    exc = context.get("exception")
    message = context.get("message", "이벤트 루프에서 처리되지 않은 예외")
    if isinstance(exc, BaseException):
        logger.error("%s", message, exc_info=exc)
    else:
        logger.error("%s", message)


async def serve(
    *,
    host: str,
    port: int,
    admin_port: int,
    stale_after: float,
    handle: LoggingHandle | None = None,
    log_max_age_seconds: float = MAX_AGE_SECONDS,
) -> None:
    """두 리스너를 동시에 띄운다. 하나가 죽으면 함께 끝난다."""
    ensure_port_free(host, port)
    ensure_port_free(ADMIN_HOST, admin_port)

    warning = exposure_warning(host)
    if warning is not None:
        print(warning, file=sys.stderr)
        logger.warning("%s", warning)

    broadcaster = handle.broadcaster if handle else None
    log_dir = handle.log_dir if handle else None
    log_file: Callable[[], Path | None] = (
        (lambda: handle.log_file) if handle else (lambda: None)
    )

    loop = asyncio.get_running_loop()
    if broadcaster is not None:
        broadcaster.bind_loop(loop)
    loop.set_exception_handler(_loop_exception_handler)

    # 닭과 달걀이다. 관리 앱은 build_stack() 에서 만들어지는데 그 앱이 봐야 할
    # uvicorn.Server 는 build_servers() 가 그다음에야 만든다. 그래서 빈 리스트를
    # 먼저 클로저에 넘기고 서버가 생긴 뒤에 채운다. 서버가 아직 없으면 종료도
    # 시작되지 않았으므로 any() 는 자연스럽게 False 다.
    #
    # 관리 쪽만 보지 않는다. Ctrl-C 는 두 리스너에 함께 가고 MCP 쪽이 먼저
    # 종료를 시작할 수 있는데, 그때 로그 스트림이 계속 열려 있으면 관리
    # 리스너가 유예 시간을 다 쓰고 결국 강제 취소로 끝난다.
    servers: list[uvicorn.Server] = []

    def shutting_down() -> bool:
        return any(server.should_exit for server in servers)

    mcp_app, admin_app, registry = build_stack(
        host=host,
        port=port,
        admin_port=admin_port,
        stale_after=stale_after,
        broadcaster=broadcaster,
        log_file=log_file,
        should_stop=shutting_down,
    )
    mcp_server, admin_server = build_servers(
        mcp_app, admin_app, host=host, port=port, admin_port=admin_port
    )
    servers.extend((mcp_server, admin_server))
    # 반드시 build_servers() **뒤**여야 한다. uvicorn.Config 생성자는 log_config
    # 와 무관하게 자기 log_level 로 uvicorn.error 의 레벨을 덮어쓰므로, 이 줄을
    # logsetup 이나 이 호출 앞에 두면 나중에 만들어지는 관리 쪽 Config
    # (log_level="warning") 가 그대로 지워 버린다. 이 레벨을 INFO 로 되돌려야
    # uvicorn 의 기동 안내와 "Waiting for connections to close..." 가 로그
    # 파일에 남는다 — 종료가 열린 연결에 막혔을 때 그것이 유일한 단서다.
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    print(f"MCP    http://{host}:{port}/mcp")
    print(f"관리   http://{ADMIN_HOST}:{admin_port}/")
    if log_dir is not None:
        print(f"로그   {log_file()}")
        # 기동 직후 한 번 청소한다. _purge_loop 는 10분 뒤에야 처음 돈다.
        _, warnings = purge_logs(
            log_dir, _utcnow(), keep=log_file(), max_age_seconds=log_max_age_seconds
        )
        for message in warnings:
            logger.warning("%s", message)
    logger.info("서버 기동 MCP=%s:%s 관리=%s:%s", host, port, ADMIN_HOST, admin_port)

    purge = asyncio.create_task(
        _purge_loop(registry, _utcnow, log_dir, log_file, log_max_age_seconds)
    )
    try:
        await asyncio.gather(mcp_server.serve(), admin_server.serve())
    finally:
        purge.cancel()
        logger.info("서버 종료")
