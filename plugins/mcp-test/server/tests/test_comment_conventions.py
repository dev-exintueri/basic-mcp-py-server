"""주석 규약 중 기계가 볼 수 있는 부분을 검사한다.

내용의 질은 사람이 본다. 여기서 잡는 것은 절이 통째로 빠지는 경우 —
특히 새 모듈을 만들면서 `## 응용할 때` 를 빠뜨리는 것이다. 그 절은
포크한 사람이 이 파일에서 무엇을 해도 되는지 아는 유일한 통로이므로,
없으면 모듈이 하나 늘 때마다 지도에 빈칸이 생긴다.

파일을 import 하지 않고 ast 로 읽는다. import 하면 모듈 수준 부작용이
테스트에 딸려 온다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mcp_test_server"
SECTION = "## 응용할 때"

# Task 2 에서 이 목록을 패키지 전체 순회로 넓힌다.
_CORE = ("mcp_server.py", "registry.py", "auth.py", "admin.py", "app.py")


def _module_paths() -> list[Path]:
    return sorted(SRC.glob("*.py"))


def _docstring(path: Path) -> str | None:
    return ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))


def test_source_directory_is_where_we_think_it_is() -> None:
    # 경로가 어긋나면 아래 테스트들이 빈 목록을 돌며 조용히 통과한다.
    assert (SRC / "app.py").is_file()
    assert len(_module_paths()) >= 11


@pytest.mark.parametrize("name", _CORE)
def test_core_modules_document_how_to_extend_them(name: str) -> None:
    doc = _docstring(SRC / name)
    assert doc is not None, f"{name} 에 모듈 독스트링이 없다"
    assert SECTION in doc, f"{name} 의 독스트링에 '{SECTION}' 절이 없다"
