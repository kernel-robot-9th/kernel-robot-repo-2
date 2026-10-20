# =============================================================================
# 파일   : scripts/review.py
# 역할   : 코드의 [검토 필요] 태그를 모아 REVIEW.md 생성 (python -m scripts.review)
# 작성일 : 2026-10-13
# 구성   :
#   - main()  app/ 아래 .py 전체 스캔
# =============================================================================
from __future__ import annotations

import datetime
import pathlib
import re

TAG = re.compile(r"\[검토 필요\]\s*(.*)")


def main() -> None:
    """app/ 아래 모든 .py에서 [검토 필요] 줄을 찾아 REVIEW.md 표로 쓴다.
    [입력] 없음
    [출력] 없음 (REVIEW.md 덮어씀, 건수 출력)
    """
    rows = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if match := TAG.search(line):
                rows.append((str(path), line_no, match.group(1).strip()))
    lines = [
        "# 검토 필요 요청", "",
        f"생성: {datetime.date.today()} — 코드의 `# [검토 필요]` 태그를 모은 목록. "
        "항목이 해결되면 코드의 태그를 지우고 이 파일을 재생성한다 (`python -m scripts.review`).",
        "", f"총 {len(rows)}건", "", "| # | 파일 | 줄 | 내용 |", "|---|---|---|---|",
    ]
    lines += [f"| {number} | `{file}` | {line_no} | {reason} |" for number, (file, line_no, reason) in enumerate(rows, 1)]
    pathlib.Path("REVIEW.md").write_text("\n".join(lines) + "\n")
    print(f"{len(rows)} items -> REVIEW.md")


if __name__ == "__main__":
    main()
