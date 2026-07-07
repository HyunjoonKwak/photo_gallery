"""폴더 이름 규칙 — 날짜 접두어 정규화.

기본 규칙: 이벤트 폴더는 `YYYY-MM-DD 이벤트명`(하이픈) 형태. 일부가 `YYYY_MM_DD`
(밑줄)로 되어 있어 이를 교정한다. **날짜 접두어의 밑줄만** 하이픈으로 바꾸고,
이벤트 이름 속 밑줄은 건드리지 않는다(의도적일 수 있음).
"""

from __future__ import annotations

import re

# 이름 맨 앞의 YYYY_MM_DD (밑줄 구분). 뒤(이벤트명)는 그대로 둔다.
_DATE_UNDERSCORE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})")


def fix_date_prefix(name: str) -> str | None:
    """이름이 `YYYY_MM_DD…` 형태면 날짜부 밑줄을 하이픈으로 바꾼 새 이름을,
    아니면(혹은 이미 하이픈이면) None 을 반환한다."""
    m = _DATE_UNDERSCORE.match(name)
    if not m:
        return None
    fixed = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" + name[m.end() :]
    return fixed if fixed != name else None
