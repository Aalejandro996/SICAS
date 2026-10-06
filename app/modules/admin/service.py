"""
Gestión de usuarios y roles (lógica pura).
  - Los usuarios se crean SIN roles. Todo cambio de rol exige solicitud (role:assign) y aprobación
    de otra persona (role:approve): ni el solicitante ni el afectado pueden aprobar.
  - Se rechaza cualquier combinación de roles que viole la segregación de funciones.
  - Protecciones: nadie se modifica a sí mismo; no se puede dejar el sistema sin administrador activo.
  - Al cambiar roles, desactivar o resetear MFA se revocan las sesiones (los permisos viajan en el token).
"""
from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.core.security.permissions import ROLES, SYS_ADMIN, find_sod_violations, permissions_for_roles
from app.modules.auth.password import Hasher, validate_password

USERNAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class AdminUser:
    id: str
    username: str
    is_active: bool = True
    roles: list[str] = field(default_factory=list)


@dataclass
class RoleRequest:
    id: str
    target_user_id: str
    role: str
    action: str                 # GRANT | REVOKE
    reason: str
    requested_by: str
    status: str = "PENDING"
    decided_by: str | None = None


class AdminRepo(Protocol):
    def find_by_username(self, username: str) -> AdminUser | None: ...
    def get_user(self, user_id: str) -> AdminUser | None: ...
    def create_user(self, username: str, email: str, full_name: str, password_hash: str, created_by: str) -> str: ...
    def set_active(self, user_id: str, active: bool) -> None: ...
    def count_active_with_role(self, role: str) -> int: ...
    def add_role(self, user_id: str, role: str, granted_by: str, approved_by: str) -> None: ...
    def remove_role(self, user_id: str, role: str) -> None: ...
    def create_request(self, req: RoleRequest) -> None: ...
    def get_request(self, request_id: str) -> RoleRequest | None: ...
    def pending_exists(self, target: str, role: str, action: str) -> bool: ...
    def decide_request(self, request_id: str, status: str, decided_by: str, note: str) -> None: ...
    def revoke_sessions(self, user_id: str) -> None: ...
    def unlock(self, user_id: str) -> None: ...
    def reset_mfa(self, user_id: str) -> None: ...


def generate_temp_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!#$%*+-=?"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if not validate_password(pw):
            return pw


class UserAdminService:
    def __init__(self, repo: AdminRepo, hasher: Hasher, audit: Callable[..., None], new_id: Callable[[], str]):
        self.repo, self.hasher, self.audit, self.new_id = repo, hasher, audit, new_id

    def _user(self, user_id: str) -> AdminUser:
        u = self.repo.get_user(user_id)
        if u is None:
            raise AdminError("NOT_FOUND", "Usuario no encontrado")
        return u

    # ---- alta ----
    def create_user(self, actor_id: str, username: str, email: str, full_name: str) -> tuple[str, str]:
        username = username.strip().lower()
        if not USERNAME_RX.match(username):
            raise AdminError("INVALID_USERNAME", "Usuario: 3-40 caracteres (letras minúsculas, números, . _ -)")
        if not EMAIL_RX.match(email.strip()) or not full_name.strip():
            raise AdminError("INVALID_DATA", "Correo o nombre inválido")
        if self.repo.find_by_username(username):
            raise AdminError("DUPLICATE", "El usuario ya existe")
        temp = generate_temp_password()
        uid = self.repo.create_user(username, email.strip().lower(), full_name.strip(), self.hasher.hash(temp), actor_id)
        self.audit("USER_CREATED", entity_type="user", entity_id=uid, after_data={"username": username})
        return uid, temp                                   # la clave temporal se muestra una sola vez

    # ---- roles con doble control ----
    def request_role_change(self, actor_id: str, target_id: str, role: str, action: str, reason: str) -> str:
        if actor_id == target_id:
            raise AdminError("SELF_CHANGE", "No puede solicitar cambios de roles para sí mismo")
        if role not in ROLES or action not in ("GRANT", "REVOKE"):
            raise AdminError("INVALID_DATA", "Rol o acción inválidos")
        if len(reason.strip()) < 10:
            raise AdminError("REASON_REQUIRED", "Indique el motivo (mínimo 10 caracteres)")
        target = self._user(target_id)
        if not target.is_active:
            raise AdminError("INACTIVE", "El usuario está inactivo")
        if action == "GRANT":
            if role in target.roles:
                raise AdminError("ALREADY_HAS_ROLE", "El usuario ya tiene ese rol")
            self._check_sod([*target.roles, role])
        else:
            if role not in target.roles:
                raise AdminError("DOES_NOT_HAVE_ROLE", "El usuario no tiene ese rol")
            self._check_last_admin(role, target)
        if self.repo.pending_exists(target_id, role, action):
            raise AdminError("PENDING_EXISTS", "Ya existe una solicitud pendiente igual")
        rid = self.new_id()
        self.repo.create_request(RoleRequest(rid, target_id, role, action, reason.strip(), actor_id))
        self.audit("ROLE_CHANGE_REQUESTED", entity_type="user", entity_id=target_id,
                   after_data={"request": rid, "role": role, "action": action, "reason": reason.strip()})
        return rid

    def decide_role_request(self, actor_id: str, actor_roles: list[str], request_id: str, approve: bool, note: str = "") -> None:
        if "role:approve" not in permissions_for_roles(actor_roles):
            raise AdminError("FORBIDDEN", "Sin permiso para aprobar cambios de roles")
        req = self.repo.get_request(request_id)
        if req is None or req.status != "PENDING":
            raise AdminError("NOT_PENDING", "Solicitud inexistente o ya resuelta")
        if actor_id in (req.requested_by, req.target_user_id):
            self.audit("ROLE_DECISION_REJECTED", outcome="DENIED", entity_type="role_request", entity_id=request_id,
                       metadata={"reason": "DOBLE_CONTROL"})
            raise AdminError("DUAL_CONTROL", "Doble control: no puede resolver una solicitud propia ni sobre usted")
        if approve:
            target = self._user(req.target_user_id)               # se revalida con el estado ACTUAL
            if not target.is_active:
                raise AdminError("INACTIVE", "El usuario está inactivo")
            if req.action == "GRANT":
                if req.role not in target.roles:
                    self._check_sod([*target.roles, req.role])
                    self.repo.add_role(target.id, req.role, req.requested_by, actor_id)
            else:
                self._check_last_admin(req.role, target)
                self.repo.remove_role(target.id, req.role)
            self.repo.revoke_sessions(target.id)                  # los permisos nuevos aplican en el próximo login
        self.repo.decide_request(request_id, "APPROVED" if approve else "REJECTED", actor_id, note)
        self.audit("ROLE_CHANGE_APPROVED" if approve else "ROLE_CHANGE_REJECTED", entity_type="user",
                   entity_id=req.target_user_id, after_data={"request": request_id, "role": req.role, "action": req.action})

    # ---- cuenta ----
    def set_active(self, actor_id: str, target_id: str, active: bool) -> None:
        if actor_id == target_id:
            raise AdminError("SELF_CHANGE", "No puede desactivar su propia cuenta")
        target = self._user(target_id)
        if not active:
            for r in target.roles:
                self._check_last_admin(r, target)
            self.repo.revoke_sessions(target_id)
        self.repo.set_active(target_id, active)
        self.audit("USER_ACTIVATED" if active else "USER_DEACTIVATED", entity_type="user", entity_id=target_id)

    def unlock(self, actor_id: str, target_id: str) -> None:
        self._user(target_id)
        self.repo.unlock(target_id)
        self.audit("USER_UNLOCKED", entity_type="user", entity_id=target_id)

    def reset_mfa(self, actor_id: str, target_id: str) -> None:
        if actor_id == target_id:
            raise AdminError("SELF_CHANGE", "No puede restablecer su propio MFA")
        self._user(target_id)
        self.repo.reset_mfa(target_id)
        self.repo.revoke_sessions(target_id)
        self.audit("USER_MFA_RESET", entity_type="user", entity_id=target_id)

    # ---- reglas internas ----
    @staticmethod
    def _check_sod(resulting_roles: list[str]) -> None:
        v = find_sod_violations(resulting_roles)
        if v:
            raise AdminError("SOD_VIOLATION", "Segregación de funciones: " + "; ".join(f"{a} + {b} ({why})" for a, b, why in v))

    def _check_last_admin(self, role: str, target: AdminUser) -> None:
        if role == SYS_ADMIN and target.is_active and self.repo.count_active_with_role(SYS_ADMIN) <= 1:
            raise AdminError("LAST_ADMIN", "No se puede dejar el sistema sin un administrador activo")
