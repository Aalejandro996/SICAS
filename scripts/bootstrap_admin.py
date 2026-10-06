"""
Crea los PRIMEROS usuarios (bootstrap), antes de que exista nadie que pueda aprobar cambios de rol.
Solo funciona mientras el rol no tenga ningún usuario activo. Cada ejecución queda en el audit trail.
Uso:
    python scripts/bootstrap_admin.py --username admin --email admin@empresa.com --name "Admin SICAS" --role SYS_ADMIN
    python scripts/bootstrap_admin.py --username contralor --email c@empresa.com --name "Contralor" --role CONTRALOR
Debe ser DOS personas distintas (SYS_ADMIN y CONTRALOR): la segregación de funciones impide acumular ambos roles.
Imprime la contraseña temporal UNA sola vez; el usuario deberá cambiarla y configurar su MFA al ingresar.
"""
import argparse
import json
import os
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from app.core.env import load_dotenv_file as load_dotenv


def main():
    # En Docker, las variables de entorno son inyectadas por Compose.
    # El archivo /srv/.env puede no existir o no ser legible dentro de la imagen.
    try:
        load_dotenv()
    except (FileNotFoundError, PermissionError):
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", required=True, choices=["SYS_ADMIN", "CONTRALOR", "AUDITOR", "GERENCIA"])
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    a = ap.parse_args()

    from sqlalchemy import create_engine, text

    from app.modules.admin.service import EMAIL_RX, USERNAME_RX, generate_temp_password
    from app.modules.auth.password import Argon2Hasher

    username = a.username.strip().lower()
    if not USERNAME_RX.match(username) or not EMAIL_RX.match(a.email):
        sys.exit("Usuario o correo inválido")
    if not a.db_url:
        sys.exit("Falta DATABASE_URL (en .env o con --db-url). Use un usuario con permisos de escritura sobre el esquema iam.")

    engine = create_engine(a.db_url)
    with engine.begin() as cx:
        # Se bloquea la tabla de usuarios para evitar que dos bootstraps simultáneos creen dos primeros usuarios
        cx.execute(text("LOCK TABLE iam.user_roles IN SHARE ROW EXCLUSIVE MODE"))
        n = cx.execute(text("SELECT count(*) FROM iam.user_roles ur JOIN iam.roles r ON r.id=ur.role_id "
                            "JOIN iam.users u ON u.id=ur.user_id WHERE r.code=:c AND u.is_active"), {"c": a.role}).scalar_one()
        if n:
            sys.exit(f"Ya existen {n} usuario(s) activo(s) con el rol {a.role}. El bootstrap solo sirve para el primero; "
                     "use la gestión de usuarios con doble control.")
        role_id = cx.execute(text("SELECT id FROM iam.roles WHERE code=:c"), {"c": a.role}).scalar()
        if role_id is None:
            sys.exit("Los roles no existen: ejecute antes sql/003_rbac_seed.sql")
        temp, uid = generate_temp_password(), str(uuid.uuid4())
        cx.execute(text("INSERT INTO iam.users (id, username, email, full_name, password_hash, must_change_password) "
                        "VALUES (CAST(:i AS uuid), :u, :e, :n, :h, true)"),
                   {"i": uid, "u": username, "e": a.email.strip().lower(), "n": a.name.strip(), "h": Argon2Hasher().hash(temp)})
        cx.execute(text("INSERT INTO iam.user_roles (user_id, role_id) VALUES (CAST(:u AS uuid), :r)"), {"u": uid, "r": role_id})
        cx.execute(text("INSERT INTO audit.audit_log (actor_username, action, entity_type, entity_id, outcome, metadata, row_hash) "
                        "VALUES ('bootstrap', 'BOOTSTRAP_USER_CREATED', 'user', :i, 'SUCCESS', CAST(:m AS jsonb), '\\x00')"),
                   {"i": uid, "m": json.dumps({"username": username, "role": a.role})})
    print(f"\nUsuario creado: {username}  (rol {a.role})\nContraseña temporal (se muestra una sola vez): {temp}\n"
          "Al ingresar deberá cambiarla y configurar su verificación en dos pasos.")


if __name__ == "__main__":
    main()
