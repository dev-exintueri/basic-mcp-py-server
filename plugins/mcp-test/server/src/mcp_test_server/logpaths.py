"""로그 파일의 위치와 이름, 그리고 오래된 파일 청소.

여기 있는 함수들은 configure_logging() 보다 먼저 돈다 — 디렉토리를 정해야
파일 핸들러를 만들 수 있기 때문이다. 그래서 경고를 직접 로깅하지 않고
문자열 목록으로 돌려주고, 호출자가 로깅이 준비된 뒤에 남긴다.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".mcp-test-server" / "logs"
MAX_AGE_SECONDS = 259200.0          # 72시간
LOG_GLOB = "mcp-test-server.*.log"

# 플러그인 ID는 <plugin-name>@<marketplace-name> 이다. 서버는 자기가 어느
# 마켓플레이스에서 설치됐는지 알 수 없으므로 접두사로만 맞춘다.
_PLUGIN_ID_PREFIX = "mcp-test@"

DEFAULT_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _clean(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _from_settings(settings_path: Path) -> tuple[Path | None, list[str]]:
    """Claude Code 사용자 설정에서 log_dir 을 읽는다.

    비민감 userConfig 값은 Claude Code 가 pluginConfigs[<plugin-id>].options
    에 직접 쓴다 (docs/claude-base/settings.md:816-834). 중계 파일도 훅도
    필요 없다.
    """
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except OSError:
        return None, []              # 파일이 없는 것은 정상이다

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, [f"{settings_path} 를 JSON 으로 읽지 못했다. 로그 경로 설정을 건너뛴다"]

    configs = data.get("pluginConfigs") if isinstance(data, dict) else None
    if not isinstance(configs, dict):
        return None, []

    matches = sorted(k for k in configs if k.startswith(_PLUGIN_ID_PREFIX))
    if not matches:
        return None, []

    warnings: list[str] = []
    chosen_key = matches[0]
    if len(matches) > 1:
        warnings.append(
            f"플러그인 설정이 {len(matches)}개 발견됐다. {chosen_key} 를 쓴다"
        )

    options = configs[chosen_key].get("options") if isinstance(configs[chosen_key], dict) else None
    if not isinstance(options, dict) or "log_dir" not in options:
        return None, warnings

    value = options["log_dir"]
    if value is None:
        return None, warnings
    if not isinstance(value, str):
        warnings.append(f"플러그인 설정의 log_dir 이 문자열이 아니다: {value!r}")
        return None, warnings
    if not value.strip():
        warnings.append("플러그인 설정의 log_dir 이 비어 있다")
        return None, warnings

    return _clean(value), warnings


def resolve_log_dir(
    *,
    flag: str | None,
    env: str | None,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> tuple[Path, list[str]]:
    """로그 디렉토리를 정한다. 앞이 이긴다.

    --log-dir > $MCP_TEST_LOG_DIR > settings.json > 기본값
    """
    if flag and flag.strip():
        return _clean(flag), []
    if env and env.strip():
        return _clean(env), []

    from_settings, warnings = _from_settings(settings_path)
    if from_settings is not None:
        return from_settings, warnings
    return DEFAULT_LOG_DIR, warnings


def log_file_name(port: int, day: date) -> str:
    return f"mcp-test-server.{port}.{day.isoformat()}.log"


def purge_logs(
    log_dir: Path,
    now: datetime,
    *,
    max_age_seconds: float = MAX_AGE_SECONDS,
    keep: Path | None = None,
) -> tuple[int, list[str]]:
    """72시간보다 오래된 로그 파일을 지운다. 지운 개수와 경고를 돌려준다.

    LOG_GLOB 에 맞는 파일만, 비재귀로 본다. log_dir 은 사용자가 지정할 수
    있으므로 무관한 파일을 지워서는 안 된다 — 홈 디렉토리를 가리켜도
    안전해야 한다.
    """
    cutoff = now.timestamp() - max_age_seconds
    keep_resolved = keep.resolve() if keep is not None else None

    removed = 0
    warnings: list[str] = []
    try:
        candidates = sorted(log_dir.glob(LOG_GLOB))
    except OSError:
        return 0, []

    for path in candidates:
        if not path.is_file():
            continue
        if keep_resolved is not None and path.resolve() == keep_resolved:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
        except OSError as exc:
            warnings.append(f"오래된 로그 {path} 를 지우지 못했다: {exc}")
            continue
        removed += 1

    return removed, warnings


def tail_lines(path: Path, *, lines: int = 200, max_bytes: int = 65536) -> list[str]:
    """파일 끝에서 최대 max_bytes 를 읽어 마지막 lines 줄을 돌려준다.

    로그 파일은 커질 수 있으므로 전체를 읽지 않는다. 잘린 첫 줄은 반쪽이라
    버린다.
    """
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            chunk = handle.read()
    except OSError:
        return []

    text = chunk.decode("utf-8", errors="replace")
    if size > max_bytes:
        _, _, text = text.partition("\n")
    return text.splitlines()[-lines:]
