"""Hallazgos de las auditorías operativas, especiales, administrativas y financieras (lógica pura).

Cada criterio de la cédula con incumplimientos (NO_CUMPLE o PARCIAL) en la muestra se agrupa por
cédula y tema normativo; cada grupo produce un hallazgo con riesgo, título, condición, criterio,
causa, efecto y recomendación. Criterio, causa, efecto y recomendación provienen del catálogo
normativo SUDEASEG (engagement.regulatory_catalog), editable por Contraloría.

Riesgo según la proporción de la muestra con incumplimiento en el peor criterio del grupo:
  ALTO >= 50 %  ·  MEDIO >= 20 %  ·  BAJO < 20 %.
"""
from __future__ import annotations

import re
import unicodedata

FAIL = ("NO_CUMPLE", "PARCIAL")
ANSWERED = ("CUMPLE", "NO_CUMPLE", "PARCIAL")
RISK_ORDER = ("BAJO", "MEDIO", "ALTO")
HIGH_RATE, MEDIUM_RATE = 0.5, 0.2
MAX_CONDITION = 3000


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def topic_for(catalog: list[dict], *texts) -> dict:
    """Tema del catálogo con más coincidencias en los textos; si ninguno coincide, el tema 'general'."""
    hay = " " + " ".join(_norm(t) for t in texts) + " "
    best, score = None, 0
    for t in sorted(catalog, key=lambda r: r.get("sort_order", 100)):
        # La palabra clave debe empezar una palabra ("rif" no coincide dentro de "verificar").
        hits = sum(1 for k in (t.get("keywords") or []) if re.search(r"(?<![a-z0-9])" + re.escape(_norm(k)), hay))
        if hits > score:
            best, score = t, hits
    return best or next((t for t in catalog if t["topic"] == "general"), catalog[-1])


def risk_for(rate: float) -> str:
    return "ALTO" if rate >= HIGH_RATE else "MEDIO" if rate >= MEDIUM_RATE else "BAJO"


def _answer(results: dict, criterion: dict):
    for key in (criterion.get("code"), criterion.get("source_id")):
        if key is not None and key in results:
            return str(results.get(key) or "").upper()
    return ""


def _short(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def findings(worksheet: dict, catalog: list[dict]) -> list[dict]:
    """Hallazgos de una cédula: uno por tema normativo con los criterios incumplidos."""
    items = worksheet.get("items") or []
    groups: dict[str, dict] = {}
    for c in worksheet.get("criteria") or []:
        answered = failed = 0
        refs, ids = [], []
        for it in items:
            v = _answer(it.get("results") or {}, c)
            if v in ANSWERED:
                answered += 1
            if v in FAIL:
                failed += 1
                refs.append(str(it.get("ref")))
                ids.append(it["id"])
        if not failed:
            continue
        topic = topic_for(catalog, c.get("section"), c.get("text"), worksheet.get("title"))
        g = groups.setdefault(topic["topic"], {"topic": topic, "rows": []})
        g["rows"].append({"code": c.get("source_id") or c.get("code"), "text": c.get("text") or "",
                          "failed": failed, "answered": answered, "rate": failed / answered if answered else 1.0,
                          "refs": refs, "ids": ids})

    title = worksheet.get("title") or "la cédula"
    out = []
    for key, g in groups.items():
        topic, rows = g["topic"], sorted(g["rows"], key=lambda r: -r["rate"])
        worst = rows[0]["rate"]
        n_items = len(items)
        condition = (f"En la revisión de «{title}» se evaluaron {n_items} ítem(s) de la muestra. Se detectaron incumplimientos "
                     f"en {len(rows)} criterio(s) de {topic['label']}:")
        listed = 0
        for r in rows:
            line = (f"\n• {r['code']}: {_short(r['text'], 140)} — {r['failed']} de {r['answered'] or n_items} "
                    f"({round(r['rate'] * 100)}%); muestra: {', '.join(r['refs'][:5])}{'…' if len(r['refs']) > 5 else ''}.")
            if len(condition) + len(line) > MAX_CONDITION - 100:
                break
            condition += line
            listed += 1
        if listed < len(rows):
            condition += f"\n• Además: {', '.join(r['code'] for r in rows[listed:])}."
        codes = [r["code"] for r in rows]
        ids = list(dict.fromkeys(i for r in rows for i in r["ids"]))
        out.append({
            "risk": risk_for(worst),
            "title": _short(f"Incumplimientos en {topic['label']} — {title} ({len(rows)} criterio{'s' if len(rows) != 1 else ''})", 200),
            "condition": condition[:MAX_CONDITION],
            "criteria": topic["criteria"], "cause": topic["cause"], "effect": topic["effect"],
            "recommendation": f"{topic['recommendation']} Criterios: {', '.join(codes)}."[:MAX_CONDITION],
            "rule_key": f"{worksheet.get('id')}:{key}", "topic": key, "controls": codes,
            "item_id": ids[0] if ids else None, "covered_items": ids,
        })
    out.sort(key=lambda o: -RISK_ORDER.index(o["risk"]))
    return out
