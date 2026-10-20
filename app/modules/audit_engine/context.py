"""
Acceso a datos del motor. Las reglas solo ven este contrato, no SQL ni Flask:
así son testeables con datos en memoria y el volumen masivo se resuelve en SqlContext
(cursores en streaming) sin tocar las reglas.

Contrato de campos (ver docs/AUDIT_ENGINE.md):
  policies():  policy_number, insured_id, risk_id, branch, start_date, end_date, sum_insured
  claims():    claim_number, policy_number, coverage, occurrence_date, reported_date, claimed_amount,
               + de la póliza: policy_start, policy_end, branch, sum_insured
  reserves():  reserve_type, branch, policy_number, claim_number, period, amount, sum_insured, currency
  payments():  payment_id, policy_number, payer_id, amount, currency, method, paid_at
  watchlist(): {identificador_normalizado: nombre_de_lista}   (cédula/RIF normalizado: V12345678)
  Todos los importes llevan `currency`; las reglas nunca mezclan monedas.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Protocol


class DataContext(Protocol):
    def policies(self) -> Iterable[dict]: ...
    def claims(self) -> Iterable[dict]: ...
    def reserves(self) -> Iterable[dict]: ...
    def payments(self) -> Iterable[dict]: ...
    def watchlist(self) -> dict[str, str]: ...


class InMemoryContext:
    def __init__(self, policies=(), claims=(), reserves=(), payments=(), watchlist=None):
        self._p, self._c, self._r = list(policies), list(claims), list(reserves)
        self._pay, self._w = list(payments), dict(watchlist or {})

    def policies(self): return iter(self._p)
    def claims(self): return iter(self._c)
    def reserves(self): return iter(self._r)
    def payments(self): return iter(self._pay)
    def watchlist(self): return dict(self._w)


class SqlContext:
    """Lectura en streaming desde PostgreSQL (réplica de lectura). Filtra opcionalmente por job_id."""

    def __init__(self, engine, job_id: str | None = None, fetch_size: int = 10_000):
        self.engine, self.job_id, self.fetch_size = engine, job_id, fetch_size

    def _stream(self, sql: str) -> Iterator[dict]:
        from sqlalchemy import text

        with self.engine.connect().execution_options(stream_results=True, yield_per=self.fetch_size) as conn:
            for row in conn.execute(text(sql), {"job_id": self.job_id}):
                yield dict(row._mapping)

    def policies(self):
        return self._stream("SELECT policy_number, insured_id, risk_id, branch, start_date, end_date, "
                            "sum_insured FROM insurance.policies WHERE (CAST(:job_id AS uuid) IS NULL OR job_id = CAST(:job_id AS uuid))")

    def claims(self):
        return self._stream("SELECT c.claim_number, c.policy_number, c.coverage, c.occurrence_date, c.reported_date, "
                            "c.claimed_amount, c.currency, p.start_date AS policy_start, p.end_date AS policy_end, "
                            "p.branch, p.sum_insured FROM insurance.claims c "
                            "LEFT JOIN LATERAL (SELECT start_date, end_date, branch, sum_insured FROM insurance.policies x "
                            "WHERE x.policy_number = c.policy_number "
                            "ORDER BY CASE WHEN c.occurrence_date BETWEEN x.start_date AND x.end_date "
                            "THEN 0 ELSE 1 END, x.id DESC LIMIT 1) p ON TRUE "
                            "WHERE (CAST(:job_id AS uuid) IS NULL OR c.job_id = CAST(:job_id AS uuid))")

    def reserves(self):
        return self._stream("SELECT id AS _id, reserve_type, branch, policy_number, claim_number, period, amount, sum_insured, currency "
                            "FROM insurance.reserves WHERE (CAST(:job_id AS uuid) IS NULL OR job_id = CAST(:job_id AS uuid))")

    def payments(self):
        return self._stream("SELECT payment_id, policy_number, payer_id, amount, currency, method, paid_at "
                            "FROM insurance.payments WHERE (CAST(:job_id AS uuid) IS NULL OR job_id = CAST(:job_id AS uuid))")

    def watchlist(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            return {r.doc_id_norm: r.list_name for r in
                    conn.execute(text("SELECT doc_id_norm, list_name FROM compliance.watchlist WHERE active"))}
