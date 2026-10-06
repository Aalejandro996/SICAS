from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class Finding:
    rule_code: str
    severity: Severity
    entity_type: str
    entity_id: str
    score: float                      # 0-100, para priorizar la revisión
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    # Hechos que identifican el hallazgo; si no cambian, no se duplica en corridas posteriores
    identity_facts: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        raw = json.dumps([self.rule_code, self.entity_type, self.entity_id, self.identity_facts],
                         sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {"rule_code": self.rule_code, "severity": self.severity.value,
                "entity_type": self.entity_type, "entity_id": self.entity_id,
                "score": round(self.score, 2), "message": self.message,
                "evidence": self.evidence, "fingerprint": self.fingerprint}
