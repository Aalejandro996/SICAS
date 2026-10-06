"""
Genera datos de PRUEBA sintéticos (ficticios) para ver SICAS trabajando: 4 CSV listos para cargar,
con anomalías sembradas a propósito para que el motor las detecte.

Uso:  python scripts/generate_sample_data.py            -> carpeta sample_data/
Cargue en este orden:  polizas.csv, siniestros.csv, reservas.csv, pagos.csv   (Cargas -> dataset correspondiente)
Luego agregue en LC/FT -> Lista restrictiva el identificador  V-99999991  y ejecute el motor.

Anomalías sembradas (el script imprime el resumen):
  pólizas:    1 número repetido, 1 par con vigencias solapadas, 1 asegurado de la lista restrictiva
  siniestros: 3 números repetidos, 3 posibles dobles reclamos, 20 muy cerca del inicio de vigencia,
              5 fuera de vigencia, 4 sin póliza, 1 ramo (HOGAR/USD) con montos fabricados (Benford)
  reservas:   3 negativas, 3 por encima de la suma asegurada, 5 atípicas
  pagos:      3 en efectivo >= 10.000 USD, 1 pagador que fracciona (4 pagos), 2 pagos de la lista restrictiva
"""
import csv
import pathlib
import random
import sys
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRANCHES = ["AUTO", "VIDA", "SALUD", "HOGAR"]
WATCH_ID = "V-99999991"


def generate(seed: int = 2026, today: date | None = None) -> dict[str, list[dict]]:
    rnd = random.Random(seed)
    today = today or date(2026, 9, 30)
    policies, claims, reserves, payments = [], [], [], []

    def money(v): return f"{v:.2f}"
    def loguniform(lo, hi): return lo * (hi / lo) ** rnd.random()

    # ---------------- pólizas ----------------
    for i in range(1, 801):
        start = today - timedelta(days=rnd.randint(60, 360))
        ccy = "USD" if rnd.random() < 0.85 else "VES"
        fx = 1 if ccy == "USD" else rnd.uniform(36, 40)
        si = loguniform(30000, 3000000) * fx
        policies.append({"policy_number": f"POL-{i:06d}", "insured_id": f"V{rnd.randint(10000000, 29999999)}",
                         "risk_id": f"R{rnd.randint(100000, 999999)}", "branch": rnd.choice(BRANCHES),
                         "start_date": start.isoformat(), "end_date": (start + timedelta(days=365)).isoformat(),
                         "sum_insured": money(si), "premium": money(si * rnd.uniform(0.02, 0.06)), "currency": ccy})
    base = list(policies)
    # número repetido
    dup = dict(base[10]); dup["insured_id"] = "V20000001"; policies.append(dup)
    # vigencias solapadas (mismo asegurado, riesgo y ramo)
    a = dict(base[20]); a["policy_number"] = "POL-900001"; a["insured_id"] = "V20000002"; a["risk_id"] = "R555555"; a["branch"] = "AUTO"
    a["start_date"], a["end_date"] = "2026-01-01", "2026-12-31"
    b = dict(a); b["policy_number"] = "POL-900002"; b["start_date"], b["end_date"] = "2026-06-01", "2027-05-31"
    policies += [a, b]
    # asegurado de la lista restrictiva
    w = dict(base[30]); w["policy_number"] = "POL-900003"; w["insured_id"] = WATCH_ID.replace("-", ""); policies.append(w)

    by_num = {p["policy_number"]: p for p in base}

    # ---------------- siniestros ----------------
    n = 0
    def add_claim(pol, occ, amount, cov=None, number=None, rep_days=None):
        nonlocal n
        n += 1
        claims.append({"claim_number": number or f"SIN-{n:06d}", "policy_number": pol["policy_number"],
                       "coverage": cov or rnd.choice(["COLISION", "ROBO", "INCENDIO", "HOSPITALIZACION", "DANOS"]),
                       "occurrence_date": occ.isoformat(), "reported_date": (occ + timedelta(days=rep_days if rep_days is not None else rnd.randint(0, 10))).isoformat(),
                       "claimed_amount": money(amount), "currency": pol["currency"]})

    for _ in range(2200):
        pol = rnd.choice(base)
        start, end = date.fromisoformat(pol["start_date"]), date.fromisoformat(pol["end_date"])
        lo, hi = start + timedelta(days=45), min(end, today)
        if lo >= hi:
            continue
        occ = lo + timedelta(days=rnd.randint(0, (hi - lo).days))
        fx = 1 if pol["currency"] == "USD" else 38
        amount = loguniform(100, 100000) * fx
        while amount > 0.9 * float(pol["sum_insured"]):          # un siniestro normal no supera la suma asegurada
            amount = loguniform(100, 100000) * fx
        add_claim(pol, occ, amount)
    normal_claims = list(claims)

    # Benford: HOGAR/USD con montos fabricados (dígitos iniciales 5-7)
    fab = 0
    for c in claims:
        if by_num[c["policy_number"]]["branch"] == "HOGAR" and c["currency"] == "USD":
            c["claimed_amount"] = money(rnd.choice([5, 6, 7]) * 10 ** rnd.randint(2, 4) + rnd.uniform(0, 99))
            fab += 1
    # duplicados exactos / dobles reclamos / tempranos / fuera de vigencia / huérfanos
    for c in rnd.sample(normal_claims, 3):
        claims.append(dict(c))
    for c in rnd.sample(normal_claims, 3):
        d = dict(c); n += 1; d["claim_number"] = f"SIN-{n:06d}"; claims.append(d)
    usd = [p for p in base if p["currency"] == "USD"]
    for k in range(20):
        pol = rnd.choice(usd); s = date.fromisoformat(pol["start_date"])
        add_claim(pol, s + timedelta(days=rnd.randint(1, 6) if k < 10 else rnd.randint(10, 25)), loguniform(500, 20000))
    for _ in range(5):
        pol = rnd.choice(usd); s = date.fromisoformat(pol["start_date"])
        add_claim(pol, s - timedelta(days=rnd.randint(3, 40)), loguniform(500, 20000))
    for k in range(4):
        add_claim({"policy_number": f"POL-NOEXISTE-{k}", "currency": "USD"}, today - timedelta(days=30 + k), 1500 + 100 * k)

    # ---------------- reservas ----------------
    ref = [c for c in normal_claims if c["currency"] == "USD" and by_num[c["policy_number"]]["branch"] == "AUTO"]
    for c in rnd.sample([c for c in normal_claims], 500):
        pol = by_num[c["policy_number"]]
        reserves.append({"reserve_type": "CLAIM", "branch": pol["branch"], "policy_number": c["policy_number"], "claim_number": c["claim_number"],
                         "period": "2026-09-01", "amount": money(float(c["claimed_amount"]) * rnd.uniform(0.6, 1.0)),
                         "sum_insured": pol["sum_insured"], "currency": pol["currency"]})
    auto_usd = [r for r in reserves if r["branch"] == "AUTO" and r["currency"] == "USD"]
    for r in rnd.sample(auto_usd, 3): r["amount"] = money(-rnd.uniform(100, 900))
    for r in rnd.sample([x for x in auto_usd if float(x["amount"]) > 0], 3): r["amount"] = money(float(r["sum_insured"]) * rnd.uniform(1.5, 3))
    for r in rnd.sample([x for x in auto_usd if float(x["amount"]) > 0], 5): r["amount"] = money(float(r["amount"]) * 80)

    # ---------------- pagos ----------------
    pid = 0
    def add_pay(pol_num, payer, amount, ccy, method, day):
        nonlocal pid
        pid += 1
        payments.append({"payment_id": f"PAG-{pid:06d}", "policy_number": pol_num, "payer_id": payer, "amount": money(amount),
                         "currency": ccy, "method": method, "paid_at": day.isoformat()})
    for p in base:
        method = rnd.choice(["TRANSFER", "TRANSFER", "CARD", "CHECK"])
        add_pay(p["policy_number"], p["insured_id"], float(p["premium"]), p["currency"], method, date.fromisoformat(p["start_date"]) + timedelta(days=rnd.randint(0, 5)))
    for _ in range(40):      # efectivo pequeño y disperso (comportamiento normal)
        p = rnd.choice(usd); add_pay(p["policy_number"], p["insured_id"], rnd.uniform(40, 400), "USD", "CASH", today - timedelta(days=rnd.randint(1, 300)))
    for k in range(3):       # efectivo >= umbral
        p = rnd.choice(usd); add_pay(p["policy_number"], f"V3000000{k}", 15000 + 2500 * k, "USD", "CASH", today - timedelta(days=40 + k))
    p = rnd.choice(usd)      # fraccionamiento: 4 pagos en efectivo bajo el umbral en 20 días
    for k, amt in enumerate([3200, 3500, 3100, 3400]):
        add_pay(p["policy_number"], "V30000099", amt, "USD", "CASH", today - timedelta(days=60 - k * 6))
    for k in range(2):       # pagador de la lista restrictiva
        add_pay("POL-900003", WATCH_ID.replace("-", ""), 800 + 100 * k, "USD", "TRANSFER", today - timedelta(days=10 + k))

    return {"polizas": policies, "siniestros": claims, "reservas": reserves, "pagos": payments}


def write(data: dict, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in data.items():
        with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    out = ROOT / "sample_data"
    data = generate()
    write(data, out)
    print(f"Datos de prueba generados en {out}/")
    for k, v in data.items():
        print(f"  {k}.csv: {len(v)} filas")
    print(f"\nAgregue en LC/FT -> Lista restrictiva el identificador {WATCH_ID} antes de ejecutar el motor.")
