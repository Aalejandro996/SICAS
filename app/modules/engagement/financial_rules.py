"""
Motor de reglas para cédulas financieras SICAS.

Primera regla oficial:
    FIN-RESP-STD

Respuesta del criterio:
    CUMPLE     = 100
    NO_CUMPLE  = 0
    NO_APLICA  = no puntúa

No define pesos ni reglas de negocio no presentes en la fuente.
No toca Auditoría de Sistemas ni audit_engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RULE_SCORED = "SCORED"
RULE_EXCLUDED = "EXCLUDED"
RULE_EXCEPTION = "EXCEPTION"
RULE_INVALID_RESPONSE = "INVALID_RESPONSE"
RULE_NOT_DEFINED = "RULE_NOT_DEFINED"

STANDARD_RULE_CODE = "FIN-RESP-STD"

STANDARD_POINTS = {
    "CUMPLE": 100.0,
    "PARCIAL": 50.0,
    "NO_CUMPLE": 0.0,
}


@dataclass(frozen=True)
class FinancialRuleDecision:
    status: str
    score: float | None
    rule_code: str | None
    reason: str
    details: dict[str, Any]


def _excluded(
    status: str,
    reason: str,
    *,
    template_code: str,
    source_id: str,
    response: Any,
) -> FinancialRuleDecision:
    return FinancialRuleDecision(
        status=status,
        score=None,
        rule_code=STANDARD_RULE_CODE,
        reason=reason,
        details={
            "template_code": template_code,
            "source_id": source_id,
            "response": response,
        },
    )


def _normalize_response(response: Any) -> str:
    return str(response or "").strip().upper()


def is_financial_criteria(
    criterion: Mapping[str, Any],
) -> bool:
    """
    Identifica exclusivamente criterios del catálogo financiero.
    """
    return str(
        criterion.get("evaluation_mode") or ""
    ).strip().upper() == "FINANCIAL_CATALOG"


def standard_response_rule(
    template_code: str,
    criterion: Mapping[str, Any],
    response: Any,
    *,
    exception: bool = False,
) -> FinancialRuleDecision:
    """
    Regla estándar de calificación de un criterio financiero.
    """

    template = str(template_code or "").strip().upper()
    source_id = str(
        criterion.get("source_id")
        or criterion.get("code")
        or ""
    ).strip()

    if not template:
        return FinancialRuleDecision(
            status=RULE_NOT_DEFINED,
            score=None,
            rule_code=None,
            reason="La cédula financiera no tiene plantilla identificada.",
            details={},
        )

    if not source_id:
        return FinancialRuleDecision(
            status=RULE_NOT_DEFINED,
            score=None,
            rule_code=None,
            reason="El criterio financiero no tiene identificador.",
            details={
                "template_code": template,
            },
        )

    # La excepción representa información no recibida.
    if exception:
        return _excluded(
            RULE_EXCEPTION,
            "Información no recibida: queda como limitación al alcance.",
            template_code=template,
            source_id=source_id,
            response=response,
        )

    normalized = _normalize_response(response)

    # No aplica: no entra al denominador.
    if normalized in {"NO_APLICA", "N/A", "NA"}:
        return _excluded(
            RULE_EXCLUDED,
            "Criterio no aplicable.",
            template_code=template,
            source_id=source_id,
            response=response,
        )

    # Respuesta vacía todavía no es una calificación.
    if normalized == "":
        return FinancialRuleDecision(
            status=RULE_NOT_DEFINED,
            score=None,
            rule_code=STANDARD_RULE_CODE,
            reason="El criterio todavía no ha sido respondido.",
            details={
                "template_code": template,
                "source_id": source_id,
            },
        )

    score = STANDARD_POINTS.get(normalized)

    if score is None:
        return FinancialRuleDecision(
            status=RULE_INVALID_RESPONSE,
            score=None,
            rule_code=STANDARD_RULE_CODE,
            reason=(
                "Respuesta no válida para un criterio financiero: "
                f"{response!r}"
            ),
            details={
                "template_code": template,
                "source_id": source_id,
                "response": response,
                "allowed": [
                    "CUMPLE",
                    "PARCIAL",
                    "NO_CUMPLE",
                    "NO_APLICA",
                    "EXCEPCION",
                ],
            },
        )

    return FinancialRuleDecision(
        status=RULE_SCORED,
        score=score,
        rule_code=STANDARD_RULE_CODE,
        reason="Criterio evaluado con la regla estándar financiera.",
        details={
            "template_code": template,
            "source_id": source_id,
            "response": normalized,
        },
    )


def evaluate_criterion(
    template_code: str,
    criterion: Mapping[str, Any],
    response: Any,
    *,
    exception: bool = False,
) -> FinancialRuleDecision:
    """
    Punto único de entrada.

    Por ahora el catálogo financiero utiliza la regla estándar.
    Las reglas específicas de negocio se agregarán explícitamente
    cuando la fuente las defina.
    """

    if not is_financial_criteria(criterion):
        return FinancialRuleDecision(
            status=RULE_NOT_DEFINED,
            score=None,
            rule_code=None,
            reason=(
                "El criterio no pertenece al catálogo FINANCIAL_CATALOG."
            ),
            details={
                "template_code": template_code,
                "source_id": criterion.get("source_id"),
                "evaluation_mode": criterion.get("evaluation_mode"),
            },
        )

    return standard_response_rule(
        template_code,
        criterion,
        response,
        exception=exception,
    )


def evaluate_worksheet(
    template_code: str,
    criteria: list[Mapping[str, Any]],
    responses: Mapping[str, Any],
    *,
    exceptions: Mapping[str, bool] | None = None,
) -> list[FinancialRuleDecision]:
    """
    Evalúa todos los criterios financieros de una cédula.
    """

    exceptions = exceptions or {}
    decisions: list[FinancialRuleDecision] = []

    for criterion in criteria:
        source_id = str(
            criterion.get("source_id")
            or criterion.get("code")
            or ""
        ).strip()

        decisions.append(
            evaluate_criterion(
                template_code,
                criterion,
                responses.get(source_id),
                exception=bool(exceptions.get(source_id)),
            )
        )

    return decisions