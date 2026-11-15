from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class AcquisitionResult:
    supported: bool
    provider: str
    status: str
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class FirmwareAcquisitionProvider:
    name = "base"

    def probe(self, target: dict) -> AcquisitionResult:
        raise NotImplementedError

    def acquire(self, target: dict, progress: Optional[Callable[[int, int, str], None]] = None) -> AcquisitionResult:
        raise NotImplementedError
