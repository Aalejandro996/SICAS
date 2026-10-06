"""Validación y normalización fila a fila por dataset. Los nombres de columna salen SOLO de SPECS (lista blanca)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

CURRENCIES = {"VES", "USD", "EUR"}
SPECS = {
    "policies": {"cols": ["policy_number", "insured_id", "risk_id", "branch", "start_date", "end_date", "sum_insured", "premium", "currency"],
                 "required": ["policy_number", "insured_id", "branch", "start_date", "end_date", "sum_insured", "premium", "currency"],
                 "dates": ["start_date", "end_date"], "amounts": ["sum_insured", "premium"], "amount_field": "premium"},
    "claims": {"cols": ["claim_number", "policy_number", "coverage", "occurrence_date", "reported_date", "claimed_amount", "currency"],
               "required": ["claim_number", "policy_number", "occurrence_date", "reported_date", "claimed_amount", "currency"],
               "dates": ["occurrence_date", "reported_date"], "amounts": ["claimed_amount"], "amount_field": "claimed_amount"},
    "reserves": {"cols": ["reserve_type", "branch", "policy_number", "claim_number", "period", "amount", "sum_insured", "currency"],
                 "required": ["reserve_type", "branch", "period", "amount", "currency"],
                 "dates": ["period"], "amounts": ["amount", "sum_insured"], "amount_field": "amount",
                 "enums": {"reserve_type": {"CLAIM", "MATHEMATICAL", "UNEARNED_PREMIUM"}}},
    "payments": {"cols": ["payment_id", "policy_number", "payer_id", "amount", "currency", "method", "paid_at"],
                 "required": ["payment_id", "policy_number", "payer_id", "amount", "currency", "method", "paid_at"],
                 "dates": ["paid_at"], "amounts": ["amount"], "amount_field": "amount",
                 "enums": {"method": {"CASH", "TRANSFER", "CARD", "CHECK", "OTHER"}}},
}
VALIDATORS = SPECS
DATASETS = set(SPECS)


def _amount(v: str) -> Decimal:
    return Decimal(v.strip().replace(",", "."))


def validate_row(dataset: str, row: dict) -> list[str]:
    spec, errors = SPECS[dataset], []
    for f in spec["required"]:
        if not (row.get(f) or "").strip():
            errors.append(f"{f}: obligatorio")
    for f in spec["dates"]:
        try:
            if (row.get(f) or "").strip():
                date.fromisoformat(row[f].strip()[:10])
        except ValueError:
            errors.append(f"{f}: fecha inválida (use AAAA-MM-DD)")
    for f in spec["amounts"]:
        try:
            if (row.get(f) or "").strip():
                v = _amount(row[f])
                if not v.is_finite():
                    raise InvalidOperation
        except InvalidOperation:
            errors.append(f"{f}: monto inválido")
    if (row.get("currency") or "").strip() and row["currency"].strip().upper() not in CURRENCIES:
        errors.append(f"currency: use {', '.join(sorted(CURRENCIES))}")
    for f, allowed in spec.get("enums", {}).items():
        if (row.get(f) or "").strip() and row[f].strip().upper() not in allowed:
            errors.append(f"{f}: valores permitidos {', '.join(sorted(allowed))}")
    if not errors:
        if dataset == "policies" and row["end_date"].strip()[:10] <= row["start_date"].strip()[:10]:
            errors.append("end_date debe ser posterior a start_date")
        if dataset == "payments" and _amount(row["amount"]) <= 0:
            errors.append("amount debe ser mayor que cero")
    return errors


def normalize_row(dataset: str, row: dict) -> dict:
    """Solo columnas conocidas; fechas AAAA-MM-DD; coma decimal -> punto; códigos en mayúscula."""
    spec, out = SPECS[dataset], {}
    for c in spec["cols"]:
        v = (row.get(c) or "").strip()
        if c in spec["dates"] and v:
            v = v[:10]
        elif c in spec["amounts"] and v:
            v = str(_amount(v))
        elif c in ("currency", "reserve_type", "method", "branch", "policy_number", "claim_number", "insured_id", "payer_id") and v:
            v = v.upper()
        out[c] = v or None
    return out
