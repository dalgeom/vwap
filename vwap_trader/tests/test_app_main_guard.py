import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import _acquire_single_instance


def test_single_instance_second_acquire_fails():
    # 같은 프로세스에서 두 번째 CreateMutexW는 ERROR_ALREADY_EXISTS
    assert _acquire_single_instance() is True
    assert _acquire_single_instance() is False
