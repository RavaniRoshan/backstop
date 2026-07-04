from __future__ import annotations

import random

from .config import BackstopConfig


def is_retryable_status(status_code: int, config: BackstopConfig) -> bool:
    return status_code in config.retry_statuses


def backoff_delay(attempt_index: int, config: BackstopConfig) -> float:
    cap = min(config.retry_max_delay, config.retry_base_delay * (2**attempt_index))
    if cap <= 0:
        return 0.0
    return random.uniform(0.0, cap)

