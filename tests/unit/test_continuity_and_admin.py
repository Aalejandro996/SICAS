"""Suplencias del flujo del informe, baja definitiva de usuarios y reglas de los motores con doble control."""
import itertools
import unittest
from datetime import date
from unittest.mock import patch

from flask import Flask, g

from app.core.security.permissions import (AUDITOR_SISTEMAS, CONTRALOR, GERENCIA, JEFE_AUDITORIA_SISTEMAS, ROLE_PERMISSIONS,
                                           SOD_CONFLICTS, SYS_ADMIN, permissions_for_roles)
from app.modules.admin.service import AdminError, UserAdminService
from app.modules.engagement import api as engagement_api
from app.modules.engagement import observation_rules
from app.modules.engagement.report_builder import actor_label
from app.modules.rules_admin.service import RuleAdminError, RulesAdminService
from tests.security.test_admin import FakeRepo, Hasher


# ------------------------------------------------------------------ baja definitiva de usuarios
class RemovalRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.removals, self.removed = {}, {}

    def is_removed(self, i): return i in self.removed
    def removal_pending(self, i): return any(q.target_user_id == i and q.status == "PENDING" for q in self.removals.values())
    def create_removal_request(self, q): self.removals[q.id] = q
    def get_removal_request(self, i): return self.removals.get(i)

    def remove_user(self, i, by, reason):
        self.removed[i] = (by, reason)
        self.users[i].is_active, self.users[i].roles = False, []

    def decide_removal(self, i, st, by, note): self.removals[i].status = st


class UserRemovalTest(unittest.TestCase):
    REASON = "Renuncia aceptada el 20/10/2026, ya no forma parte del equipo"

    def setUp(self):
        self.repo = RemovalRepo()
        self.repo.add("adm1", "admin1", [SYS_ADMIN]); self.repo.add("adm2", "admin2", [SYS_ADMIN])
        self.repo.add("con1", "contralor1", [CONTRALOR]); self.repo.add("aud1", "auditor1", [AUDITOR_SISTEMAS])
        ids = itertools.count(1)
        self.svc = UserAdminService(self.repo, Hasher(), lambda *a, **k: self.repo.log.append((a, k)), lambda: f"q{next(ids)}")

    def test_request_then_contralor_approves_logical_removal(self):
        rid = self.svc.request_removal("adm1", "aud1", self.REASON)
        self.assertTrue(self.repo.users["aud1"].is_active)                          # aún no se aplica
        self.svc.decide_removal("con1", [CONTRALOR], rid, True, "Conforme")
        self.assertFalse(self.repo.users["aud1"].is_active)
        self.assertEqual(self.repo.users["aud1"].roles, [])
        self.assertIn("aud1", self.repo.sessions_revoked)
        self.assertEqual(self.repo.removed["aud1"], ("con1", self.REASON))
        self.assertEqual(self.repo.removals[rid].status, "APPROVED")

    def test_justification_self_and_duplicates(self):
        with self.assertRaises(AdminError) as c:
            self.svc.request_removal("adm1", "aud1", "corta")
        self.assertEqual(c.exception.code, "REASON_REQUIRED")
        with self.assertRaises(AdminError) as c:
            self.svc.request_removal("adm1", "adm1", self.REASON)
        self.assertEqual(c.exception.code, "SELF_CHANGE")
        self.svc.request_removal("adm1", "aud1", self.REASON)
        with self.assertRaises(AdminError) as c:
            self.svc.request_removal("adm2", "aud1", self.REASON)
        self.assertEqual(c.exception.code, "PENDING_EXISTS")

    def test_dual_control_and_permission(self):
        rid = self.svc.request_removal("adm1", "aud1", self.REASON)
        for actor in ("adm1", "aud1"):
            with self.assertRaises(AdminError) as c:
                self.svc.decide_removal(actor, [CONTRALOR], rid, True)
            self.assertEqual(c.exception.code, "DUAL_CONTROL")
        with self.assertRaises(AdminError) as c:
            self.svc.decide_removal("adm2", [SYS_ADMIN], rid, True)
        self.assertEqual(c.exception.code, "FORBIDDEN")
        self.assertNotIn("aud1", self.repo.removed)

    def test_last_admin_cannot_be_removed(self):
        rid = self.svc.request_removal("adm1", "adm2", self.REASON)              # con dos administradores se admite
        self.repo.users["adm1"].is_active = False                                  # al decidir queda uno solo
        with self.assertRaises(AdminError) as c:
            self.svc.decide_removal("con1", [CONTRALOR], rid, True)
        self.assertEqual(c.exception.code, "LAST_ADMIN")
        self.assertNotIn("adm2", self.repo.removed)

    def test_rejected_request_changes_nothing_and_removed_cannot_be_reactivated(self):
        rid = self.svc.request_removal("adm1", "aud1", self.REASON)
        self.svc.decide_removal("con1", [CONTRALOR], rid, False, "Sigue en el equipo")
        self.assertTrue(self.repo.users["aud1"].is_active)
        rid = self.svc.request_removal("adm1", "aud1", self.REASON)
        self.svc.decide_removal("con1", [CONTRALOR], rid, True)
        with self.assertRaises(AdminError) as c:
            self.svc.set_active("adm1", "aud1", True)
        self.assertEqual(c.exception.code, "ALREADY_REMOVED")
        with self.assertRaises(AdminError) as c:
            self.svc.request_removal("adm1", "aud1", self.REASON)
        self.assertEqual(c.exception.code, "ALREADY_REMOVED")


# ------------------------------------------------------------------ reglas de los motores
class FakeRulesRepo:
    def __init__(self):
        self.rows = {("SUDEASEG", "general"): self.row("Tema general", []), ("SUDEASEG", "pagos"): self.row("Pagos", ["pago"])}
        self.reqs, self.applied = {}, []

    @staticmethod
    def row(label, kws, **kw):
        return {"label": label, "keywords": kws, "criteria": "Criterio normativo vigente", "cause": "Causa del incumplimiento",
                "effect": "Efecto sobre la empresa", "recommendation": "Recomendación aplicable", "sort_order": 100, "active": True, **kw}

    def current(self, e, k):
        return dict(self.rows[(e, k)]) if (e, k) in self.rows else None

    def pending_exists(self, e, k): return any(q.engine == e and q.rule_key == k and q.status == "PENDING" for q in self.reqs.values())
    def create_request(self, q): self.reqs[q.id] = q
    def get_request(self, i): return self.reqs.get(i)

    def apply(self, e, k, values, actor, is_new):
        self.applied.append((e, k, is_new))
        self.rows[(e, k)] = dict(values)

    def decide(self, i, st, by, note): self.reqs[i].status = st


ANALYTIC = {"EARLY_CLAIM": {"high_days": 7, "medium_days": 30}}


class RulesAdminTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRulesRepo()
        ids = itertools.count(1)
        self.log = []
        self.svc = RulesAdminService(self.repo, lambda *a, **k: self.log.append(a[0]), lambda: f"c{next(ids)}", ANALYTIC.get)

    def test_change_needs_approval_by_someone_else(self):
        rid = self.svc.propose("adm1", "SUDEASEG", "pagos", {"keywords": ["pago", "egreso"]}, "Agregar la palabra egreso")
        self.assertEqual(self.repo.rows[("SUDEASEG", "pagos")]["keywords"], ["pago"])  # aún no se aplica
        with self.assertRaises(RuleAdminError) as c:
            self.svc.decide("adm1", {"rule:configure"}, rid, True)
        self.assertEqual(c.exception.code, "DUAL_CONTROL")
        with self.assertRaises(RuleAdminError) as c:
            self.svc.decide("adm2", {"rule:propose"}, rid, True)
        self.assertEqual(c.exception.code, "FORBIDDEN")
        self.assertEqual(self.svc.decide("con1", {"rule:configure"}, rid, True), "APPROVED")
        self.assertEqual(self.repo.rows[("SUDEASEG", "pagos")]["keywords"], ["pago", "egreso"])
        self.assertEqual(self.repo.applied, [("SUDEASEG", "pagos", False)])
        self.assertIn("RULE_CHANGE_APPROVED", self.log)

    def test_new_rule_requires_all_fields_and_valid_key(self):
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "SISTEMAS", "nube", {"label": "Nube"}, "Nuevo dominio de nube")
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "SISTEMAS", "Nube Privada", {"label": "Nube"}, "Nuevo dominio de nube")
        payload = {"label": "servicios en la nube", "keywords": ["nube", "saas"], "criteria": "ISO/IEC 27001:2022 A 5.23",
                   "cause": "No existe política de nube", "effect": "Exposición de datos en terceros",
                   "recommendation": "Aprobar una política de uso de nube", "field_test": "Revisar contratos y configuración"}
        rid = self.svc.propose("adm1", "SISTEMAS", "nube", payload, "Nuevo dominio de nube")
        self.svc.decide("con1", {"rule:configure"}, rid, True)
        self.assertEqual(self.repo.applied, [("SISTEMAS", "nube", True)])
        self.assertFalse(self.repo.rows[("SISTEMAS", "nube")]["critical"])

    def test_general_rule_cannot_be_deactivated_and_active_rule_needs_keywords(self):
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "SUDEASEG", "general", {"active": False}, "Desactivar la regla general")
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "SUDEASEG", "pagos", {"keywords": []}, "Quitar todas las palabras clave")
        self.svc.propose("adm1", "SUDEASEG", "pagos", {"keywords": [], "active": False}, "Desactivar la regla de pagos")

    def test_reason_no_change_and_one_pending_per_rule(self):
        with self.assertRaises(RuleAdminError) as c:
            self.svc.propose("adm1", "SUDEASEG", "pagos", {"label": "Pagos 2"}, "corto")
        self.assertEqual(c.exception.code, "REASON_REQUIRED")
        with self.assertRaises(RuleAdminError) as c:
            self.svc.propose("adm1", "SUDEASEG", "pagos", {"label": "Pagos"}, "Mismo texto que el vigente")
        self.assertEqual(c.exception.code, "NO_CHANGE")
        self.svc.propose("adm1", "SUDEASEG", "pagos", {"label": "Pagos y egresos"}, "Ampliar el nombre del tema")
        with self.assertRaises(RuleAdminError) as c:
            self.svc.propose("adm2", "SUDEASEG", "pagos", {"label": "Egresos"}, "Otra propuesta simultánea")
        self.assertEqual(c.exception.code, "PENDING_EXISTS")

    def test_stale_proposal_is_not_applied(self):
        rid = self.svc.propose("adm1", "SUDEASEG", "pagos", {"label": "Pagos y egresos"}, "Ampliar el nombre del tema")
        self.repo.rows[("SUDEASEG", "pagos")]["cause"] = "Causa editada por Contraloría mientras tanto"
        with self.assertRaises(RuleAdminError) as c:
            self.svc.decide("con1", {"rule:configure"}, rid, True)
        self.assertEqual(c.exception.code, "STALE")
        self.assertEqual(self.repo.applied, [])

    def test_analytic_parameters_are_validated(self):
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "ANALITICO", "EARLY_CLAIM", {"params": {"unknown": 1}}, "Parámetro inexistente")
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm1", "ANALITICO", "EARLY_CLAIM", {"params": {"high_days": "siete"}}, "Tipo incorrecto del valor")
        with self.assertRaises(RuleAdminError) as c:
            self.svc.propose("adm1", "ANALITICO", "NEW_RULE", {"params": {}}, "Regla analítica nueva")
        self.assertEqual(c.exception.code, "NOT_FOUND")
        rid = self.svc.propose("adm1", "ANALITICO", "EARLY_CLAIM", {"params": {"high_days": 10}}, "Ampliar la ventana de alerta")
        self.svc.decide("con1", {"rule:configure"}, rid, True)
        self.assertEqual(self.repo.rows[("ANALITICO", "EARLY_CLAIM")], {"params": {"high_days": 10}, "enabled": True})


class RbacTest(unittest.TestCase):
    def test_admin_proposes_and_contralor_approves(self):
        self.assertIn("rule:propose", ROLE_PERMISSIONS[SYS_ADMIN])
        self.assertNotIn("rule:configure", ROLE_PERMISSIONS[SYS_ADMIN])
        self.assertIn("rule:configure", ROLE_PERMISSIONS[CONTRALOR])
        self.assertNotIn("rule:propose", ROLE_PERMISSIONS[CONTRALOR])
        self.assertIn(("rule:propose", "rule:configure"), [(a, b) for a, b, _ in SOD_CONFLICTS])


# ------------------------------------------------------------------ motor de Sistemas desde la base de datos
def rows_from_builtin():
    return [{"domain_key": d.key, "label": d.label, "keywords": list(d.keywords), "criteria": d.criteria, "cause": d.cause,
             "effect": d.effect, "recommendation": d.recommendation, "field_test": d.test, "critical": d.critical,
             "sort_order": 999 if d.key == "general" else (i + 1) * 10, "active": True}
            for i, d in enumerate(observation_rules.DOMAINS + (observation_rules.DEFAULT_DOMAIN,))]


class SystemsCatalogTest(unittest.TestCase):
    SAMPLES = [("Accesos", "¿Existe revisión periódica de usuarios privilegiados?"),
               ("Respaldo", "¿Se realizan pruebas de restauración de las copias de seguridad?"),
               ("Gobierno", "¿Existe una política de seguridad aprobada?"), ("", "Pregunta sin dominio reconocible")]

    def test_seeded_catalog_matches_builtin_engine(self):
        domains = observation_rules.domains_from_rows(rows_from_builtin())
        self.assertEqual(domains, observation_rules.DOMAINS + (observation_rules.DEFAULT_DOMAIN,))
        for section, question in self.SAMPLES:
            self.assertEqual(observation_rules.domain_for(section, question, domains).key,
                             observation_rules.domain_for(section, question).key)

    def test_inactive_domains_are_skipped_and_general_is_the_fallback(self):
        rows = rows_from_builtin()
        for r in rows:
            if r["domain_key"] == "accesos":
                r["active"] = False
        domains = observation_rules.domains_from_rows(rows)
        self.assertNotIn("accesos", [d.key for d in domains])
        self.assertEqual(domains[-1].key, "general")
        self.assertNotEqual(observation_rules.domain_for("Accesos", "¿Se revisan los usuarios privilegiados?", domains).key, "accesos")

    def test_new_domain_drafts_observations_with_its_texts(self):
        rows = rows_from_builtin() + [{"domain_key": "nube", "label": "servicios en la nube", "keywords": ["Nube"], "criteria": "Criterio nube",
                                       "cause": "Causa nube", "effect": "Efecto nube", "recommendation": "Recomendación nube",
                                       "field_test": "Prueba nube", "critical": False, "sort_order": 5, "active": True}]
        domains = observation_rules.domains_from_rows(rows)
        obs = observation_rules.draft({"code": "N-1", "text": "¿Se usa nube pública para el correo?"},
                                      {"control": "NO"}, domains=domains)
        self.assertEqual(obs["domain"], "nube")
        self.assertEqual(obs["criteria"], "Criterio nube")
        self.assertEqual(observation_rules.field_test_for({"text": "Configuración de la nube"}, domains), "Prueba nube")

    def test_empty_catalog_uses_builtin(self):
        self.assertEqual(observation_rules.domains_from_rows([]), observation_rules.DOMAINS + (observation_rules.DEFAULT_DOMAIN,))


# ------------------------------------------------------------------ suplencias
def delegation(stage, domain=None, did="d1", titular="t1"):
    return {"id": did, "stage": stage, "audit_domain": domain, "titular_id": titular, "titular_name": "Titular Uno",
            "ends_on": date(2026, 12, 31)}


class DelegationPermissionsTest(unittest.TestCase):
    def run_as(self, own, rows=None, fail=False):
        app = Flask("delegation-test")
        ctx = app.test_request_context()
        ctx.push()
        self.addCleanup(ctx.pop)
        g.claims = {"perms": sorted(own)}

        def fake(uid):
            if fail:
                raise RuntimeError("db down")
            return rows or []
        patches = [patch.object(engagement_api, "me", return_value="u1"),
                   patch.object(engagement_api.repo, "active_delegations", side_effect=fake),
                   patch.object(engagement_api.repo.db, "session")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_delegate_receives_only_the_stage_permissions(self):
        own = permissions_for_roles([AUDITOR_SISTEMAS])
        self.run_as(own, [delegation("JEFE", "SISTEMAS")])
        p = engagement_api.perms()
        self.assertIn("audit:report_approve_jefe", p)
        self.assertIn("audit:systems_review", p)
        self.assertNotIn("audit:report_approve", p)
        self.assertNotIn("audit:sign_gerente", p)
        self.assertEqual(engagement_api.acting_delegation("JEFE", "SISTEMAS")["id"], "d1")
        self.assertIsNone(engagement_api.acting_delegation("JEFE", "FINANCIERA"))
        self.assertIsNone(engagement_api.acting_delegation("GERENCIA"))

    def test_titular_acts_with_own_roles(self):
        self.run_as(permissions_for_roles([JEFE_AUDITORIA_SISTEMAS]), [delegation("JEFE", "SISTEMAS")])
        self.assertIsNone(engagement_api.acting_delegation("JEFE", "SISTEMAS"))

    def test_delegation_that_would_break_segregation_is_ignored(self):
        # Un auditor (audit:manage, audit:report_draft) no puede cubrir al Contralor ni a Gerencia.
        self.run_as(permissions_for_roles([AUDITOR_SISTEMAS]), [delegation("CONTRALOR"), delegation("GERENCIA", did="d2")])
        p = engagement_api.perms()
        self.assertNotIn("audit:sign_contralor", p)
        self.assertNotIn("audit:sign_gerente", p)
        self.assertIsNone(engagement_api.acting_delegation("CONTRALOR"))

    def test_failed_lookup_grants_nothing(self):
        own = permissions_for_roles([AUDITOR_SISTEMAS])
        self.run_as(own, fail=True)
        self.assertEqual(engagement_api.perms(), own)

    def test_gerencia_delegate_gets_signing_stage(self):
        self.run_as(permissions_for_roles([GERENCIA]) - {"audit:sign_gerente"}, [delegation("GERENCIA")])
        self.assertTrue({"audit:sign_gerente", "audit:report_approve_gerente"} <= engagement_api.perms())
        self.assertEqual(engagement_api.acting_delegation("GERENCIA")["titular_id"], "t1")


class DelegateEligibilityTest(unittest.TestCase):
    def problem(self, roles, stage, domain=None):
        return engagement_api._delegate_problem({"roles": roles}, permissions_for_roles(roles), stage, domain)

    def test_jefe_delegate_must_be_from_the_domain(self):
        self.assertIsNone(self.problem([AUDITOR_SISTEMAS], "JEFE", "SISTEMAS"))
        self.assertIsNotNone(self.problem([AUDITOR_SISTEMAS], "JEFE", "FINANCIERA"))

    def test_segregation_and_admin_exclusions(self):
        self.assertIn("Segregación", self.problem([AUDITOR_SISTEMAS], "CONTRALOR"))
        self.assertIn("Segregación", self.problem([CONTRALOR], "GERENCIA"))
        self.assertIsNotNone(self.problem([SYS_ADMIN], "CONTRALOR"))
        self.assertIsNotNone(self.problem([GERENCIA], "GERENCIA"))       # ya cumple la función
        self.assertIsNone(self.problem([], "CONTRALOR"))


class OnBehalfLabelTest(unittest.TestCase):
    def test_label(self):
        self.assertEqual(actor_label({"actor_username": "jperez"}), "jperez")
        self.assertEqual(actor_label({"actor_username": "jperez", "on_behalf_of": "Ana Ruiz"}),
                         "jperez (suplente, en nombre de Ana Ruiz)")


if __name__ == "__main__":
    unittest.main()
