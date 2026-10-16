import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheDomainMetrics:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    errors: int = 0
    bypassed: int = 0

    @property
    def total_reads(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        total = self.total_reads
        return round(self.hits / total, 4) if total > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "errors": self.errors,
            "bypassed": self.bypassed,
            "total_reads": self.total_reads,
            "hit_ratio": self.hit_ratio,
        }


class CacheMetrics:
    """Thread-safe metrics accumulator for cache operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._domains: dict[str, CacheDomainMetrics] = {
            "graph": CacheDomainMetrics(),
            "route": CacheDomainMetrics(),
            "risk": CacheDomainMetrics(),
        }

    def _get_domain(self, domain: str) -> CacheDomainMetrics:
        if domain not in self._domains:
            self._domains[domain] = CacheDomainMetrics()
        return self._domains[domain]

    def record_hit(self, domain: str) -> None:
        with self._lock:
            self._get_domain(domain).hits += 1

    def record_miss(self, domain: str) -> None:
        with self._lock:
            self._get_domain(domain).misses += 1

    def record_set(self, domain: str) -> None:
        with self._lock:
            self._get_domain(domain).sets += 1

    def record_error(self, domain: str) -> None:
        with self._lock:
            self._get_domain(domain).errors += 1

    def record_bypassed(self, domain: str) -> None:
        with self._lock:
            self._get_domain(domain).bypassed += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            domain_snapshots = {
                domain: metrics.as_dict() for domain, metrics in self._domains.items()
            }
            total_hits = sum(m.hits for m in self._domains.values())
            total_misses = sum(m.misses for m in self._domains.values())
            total_sets = sum(m.sets for m in self._domains.values())
            total_errors = sum(m.errors for m in self._domains.values())
            total_bypassed = sum(m.bypassed for m in self._domains.values())
            total_reads = total_hits + total_misses
            total_hit_ratio = round(total_hits / total_reads, 4) if total_reads > 0 else 0.0

            return {
                "overall": {
                    "hits": total_hits,
                    "misses": total_misses,
                    "sets": total_sets,
                    "errors": total_errors,
                    "bypassed": total_bypassed,
                    "total_reads": total_reads,
                    "hit_ratio": total_hit_ratio,
                },
                "domains": domain_snapshots,
            }

    def reset(self) -> None:
        with self._lock:
            self._domains = {
                "graph": CacheDomainMetrics(),
                "route": CacheDomainMetrics(),
                "risk": CacheDomainMetrics(),
            }
