#!/bin/sh
# headersHelper — Claude Code가 연결마다 한 번(세션 시작과 재연결 시점)
# 실행한다. 여기서 발급한 ID가 그 연결의 모든 요청에 실린다.
#
# userConfig 값을 가리키는 치환 문법을 여기에 쓰면 안 된다. 이 명령은
# 셸을 거치므로 Claude Code가 치환을 거부하고 서버를 misconfigured로 표시한다.
set -eu

id=$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')
short=$(printf '%s' "$id" | tr -d '-' | cut -c1-12)

printf '{"X-Client-Instance": "%s"}\n' "$short"
