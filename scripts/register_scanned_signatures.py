#!/usr/bin/env python3
"""
Registra las firmas escaneadas en engagement.signature_assets.

SEGURIDAD:
- NO lee, cambia, mueve ni regenera secrets/.
- Guarda el PNG en PostgreSQL (BYTEA), no en /static, para evitar exponer la firma por URL publica.
- Por defecto NO reemplaza una firma activa diferente; exige --replace de forma explicita.
- La asociacion se hace por nombre completo normalizado y exige una coincidencia unica.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
import zipfile
from pathlib import PurePosixPath

from sqlalchemy import text

from app import create_app
from app.extensions import db

PEOPLE = {
    "Adrian Munoz": {"display_name": "Adrian Muñoz", "role_hint": "AUDITOR_SISTEMAS", "domain": "SISTEMAS"},
    "Carlos Gomez": {"display_name": "Carlos Gómez", "role_hint": "JEFE_AUDITORIA_SISTEMAS", "domain": "SISTEMAS"},
    "Anderson Blanco": {"display_name": "Anderson Blanco", "role_hint": "JEFE_AUDITORIA_FINANCIERA", "domain": "FINANCIERA"},
    "Zaira Diaz": {"display_name": "Zaira Diaz", "role_hint": "AUDITOR_FINANCIERO", "domain": "FINANCIERA"},
    "Juan Mena": {"display_name": "Juan Mena", "role_hint": "AUDITOR_FINANCIERO", "domain": "FINANCIERA"},
    "Emyerbeth Velasquez": {"display_name": "Emyerbeth Velasquez", "role_hint": "AUDITOR_FINANCIERO", "domain": "FINANCIERA"},
    "Luis Pulido": {"display_name": "Luis Pulido", "role_hint": "GERENCIA", "domain": "GERENCIA"},
    "Patricia Parraga": {"display_name": "Patricia Parraga", "role_hint": "CONTRALOR", "domain": "CONTRALORIA"},
}


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("El archivo no es un PNG valido")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise ValueError("El PNG no contiene dimensiones validas")
    return width, height


def canonical_person_from_filename(filename: str) -> str | None:
    stem = PurePosixPath(filename).stem
    normalized = normalize_name(stem)
    for key in PEOPLE:
        if normalized == normalize_name(key):
            return key
    return None


def signature_type_from_path(filename: str) -> str | None:
    parts = [normalize_name(p) for p in PurePosixPath(filename).parts]
    if "completas" in parts:
        return "COMPLETA"
    if "media firma" in parts:
        return "MEDIA"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Registra firmas escaneadas de SICAS.")
    parser.add_argument("zip_path", help="ZIP con Firmas/Completas y Firmas/Media Firma")
    parser.add_argument("--replace", action="store_true", help="Desactiva el activo anterior cuando el hash cambia")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        try:
            with zipfile.ZipFile(args.zip_path) as zf:
                files = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".png")]
                if not files:
                    raise ValueError("El ZIP no contiene PNG")

                selected = []
                for filename in files:
                    person = canonical_person_from_filename(filename)
                    sig_type = signature_type_from_path(filename)
                    if person and sig_type:
                        selected.append((filename, person, sig_type))

                expected = {(person, sig_type) for person in PEOPLE for sig_type in ("COMPLETA", "MEDIA")}
                found = {(person, sig_type) for _, person, sig_type in selected}
                missing = sorted(expected - found)
                if missing:
                    raise ValueError("Faltan firmas requeridas: " + ", ".join(f"{p}/{t}" for p, t in missing))

                ambiguous = []
                for person, sig_type in expected:
                    matches = [x for x in selected if x[1] == person and x[2] == sig_type]
                    if len(matches) != 1:
                        ambiguous.append((person, sig_type, [m[0] for m in matches]))
                if ambiguous:
                    raise ValueError(f"Hay archivos ambiguos: {ambiguous}")

                user_rows = db.session.execute(text("SELECT id::text AS id, full_name FROM iam.users WHERE is_active = TRUE")).mappings().all()
                by_name = {}
                for row in user_rows:
                    by_name.setdefault(normalize_name(row["full_name"]), []).append(row)

                inserts = 0
                skips = 0
                for filename, person, sig_type in sorted(selected, key=lambda x: (x[1], x[2])):
                    person_meta = PEOPLE[person]
                    candidates = by_name.get(normalize_name(person_meta["display_name"]), [])
                    if len(candidates) != 1:
                        raise ValueError(
                            f"No existe una coincidencia unica en iam.users para {person_meta['display_name']}. "
                            f"Coincidencias activas: {len(candidates)}"
                        )
                    user_id = candidates[0]["id"]
                    data = zf.read(filename)
                    width, height = png_dimensions(data)
                    sha = hashlib.sha256(data).hexdigest()

                    active = db.session.execute(text("""
                        SELECT id::text AS id, sha256, original_filename
                        FROM engagement.signature_assets
                        WHERE user_id = CAST(:u AS uuid)
                          AND signature_type = :t
                          AND active = TRUE
                        ORDER BY created_at DESC
                        LIMIT 1
                    """), {"u": user_id, "t": sig_type}).mappings().first()

                    if active and active["sha256"] == sha:
                        skips += 1
                        continue
                    if active and not args.replace:
                        raise ValueError(
                            f"Ya existe una firma activa distinta para {person_meta['display_name']} / {sig_type}. "
                            "No se reemplazara automaticamente; use --replace si fue intencional."
                        )
                    if active and args.replace:
                        db.session.execute(text("UPDATE engagement.signature_assets SET active = FALSE WHERE id = CAST(:i AS uuid)"), {"i": active["id"]})

                    db.session.execute(text("""
                        INSERT INTO engagement.signature_assets
                        (user_id, signature_type, original_filename, mime_type, size_bytes, width_px, height_px, sha256, content, active, created_by)
                        VALUES
                        (CAST(:u AS uuid), :t, :f, 'image/png', :z, :w, :h, :s, :c, TRUE, NULL)
                    """), {
                        "u": user_id,
                        "t": sig_type,
                        "f": filename,
                        "z": len(data),
                        "w": width,
                        "h": height,
                        "s": sha,
                        "c": data,
                    })
                    inserts += 1

                db.session.commit()
                print(f"Firmas registradas: {inserts}; ya existentes sin cambios: {skips}; total esperado: 16")
                return 0
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
