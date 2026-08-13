from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import random
import time


@dataclass(frozen=True)
class ScrapeSafetyConfig:
    min_delay_seconds: float = 5
    max_delay_seconds: float = 15
    page_load_timeout_ms: int = 30_000
    selector_timeout_ms: int = 10_000
    max_attempts_per_run: int = 1


DEFAULT_SCRAPE_SAFETY_CONFIG = ScrapeSafetyConfig()


def polite_delay_seconds(
    *,
    rng: random.Random | None = None,
    config: ScrapeSafetyConfig = DEFAULT_SCRAPE_SAFETY_CONFIG,
) -> float:
    rng = rng or random.Random()
    return rng.uniform(config.min_delay_seconds, config.max_delay_seconds)


def wait_polite_delay(
    *,
    sleeper: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    config: ScrapeSafetyConfig = DEFAULT_SCRAPE_SAFETY_CONFIG,
) -> float:
    delay = polite_delay_seconds(rng=rng, config=config)
    sleeper(delay)
    return delay


def should_attempt_item(attempts: int, *, config: ScrapeSafetyConfig = DEFAULT_SCRAPE_SAFETY_CONFIG) -> bool:
    return attempts < config.max_attempts_per_run


def scrape_safety_summary(config: ScrapeSafetyConfig = DEFAULT_SCRAPE_SAFETY_CONFIG) -> dict[str, object]:
    return asdict(config)
