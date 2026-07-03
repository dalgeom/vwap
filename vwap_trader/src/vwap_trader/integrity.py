"""데이터 무결성 가드 순수함수 (A-3). 봇 실행 없이 테스트 가능."""
from pathlib import Path


def count_lines(path) -> int:
    """파일의 줄 수. 없으면 0."""
    p = Path(path)
    if not p.exists():
        return 0
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def check_integrity(start_lines: int, appended: int, actual_lines: int) -> str | None:
    """종료 시 실제 줄 수가 (시작 + 봇append)와 다르면 경고 메시지, 같으면 None."""
    expected = start_lines + appended
    if actual_lines != expected:
        return (f"trades 무결성 경고: 시작 {start_lines} + 봇append {appended} "
                f"= 기대 {expected}, 실제 {actual_lines} (차 {actual_lines - expected})")
    return None
