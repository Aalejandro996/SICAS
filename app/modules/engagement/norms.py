"""Catálogo normativo único del motor de reglas (base incorporada; la copia editable vive en engagement.norms).

Cada control de las plantillas de aplicativos cita códigos de este catálogo, y el motor arma con ellos el «criterio»
de cada hallazgo. Estado POR_VALIDAR: la referencia proviene de la matriz de Contraloría o de una norma cuya
providencia o artículo exacto debe confirmar el área legal antes de citarla como definitiva.
"""
from __future__ import annotations

SOURCES = {"ISO27001": "ISO/IEC 27001:2022", "COBIT": "COBIT 2019", "LEY_VE": "Legislación venezolana",
           "SUDEASEG": "Normativa SUDEASEG", "CIS": "CIS Controls v8"}

# (código, fuente, referencia, título, resumen, estado)
NORMS = [
    ("ISO-A.5.3", "ISO27001", "Anexo A 5.3", "Segregación de funciones", "Las funciones y áreas de responsabilidad en conflicto deben segregarse.", "VIGENTE"),
    ("ISO-A.5.15", "ISO27001", "Anexo A 5.15", "Control de acceso", "Reglas de control de acceso físico y lógico según requisitos de negocio y de seguridad.", "VIGENTE"),
    ("ISO-A.5.16", "ISO27001", "Anexo A 5.16", "Gestión de identidades", "Ciclo de vida completo de las identidades, incluidas las cuentas técnicas.", "VIGENTE"),
    ("ISO-A.5.17", "ISO27001", "Anexo A 5.17", "Información de autenticación", "Asignación y gestión controlada de contraseñas y demás información de autenticación.", "VIGENTE"),
    ("ISO-A.5.18", "ISO27001", "Anexo A 5.18", "Derechos de acceso", "Provisión, revisión periódica, modificación y retiro de los derechos de acceso.", "VIGENTE"),
    ("ISO-A.5.29", "ISO27001", "Anexo A 5.29", "Seguridad durante una interrupción", "Mantener la seguridad de la información durante una disrupción.", "VIGENTE"),
    ("ISO-A.5.30", "ISO27001", "Anexo A 5.30", "Preparación de las TIC para la continuidad", "Planificar, implantar, mantener y probar la preparación de las TIC.", "VIGENTE"),
    ("ISO-A.5.33", "ISO27001", "Anexo A 5.33", "Protección de registros", "Proteger los registros contra pérdida, destrucción, falsificación y acceso no autorizado.", "VIGENTE"),
    ("ISO-A.5.34", "ISO27001", "Anexo A 5.34", "Privacidad y protección de datos personales", "Cumplir los requisitos legales sobre privacidad y datos personales.", "VIGENTE"),
    ("ISO-A.8.2", "ISO27001", "Anexo A 8.2", "Derechos de acceso privilegiado", "Restringir y gestionar la asignación y uso de privilegios.", "VIGENTE"),
    ("ISO-A.8.4", "ISO27001", "Anexo A 8.4", "Acceso al código fuente", "Gestionar adecuadamente el acceso de lectura y escritura al código fuente.", "VIGENTE"),
    ("ISO-A.8.5", "ISO27001", "Anexo A 8.5", "Autenticación segura", "Tecnologías y procedimientos de autenticación segura según las restricciones de acceso.", "VIGENTE"),
    ("ISO-A.8.6", "ISO27001", "Anexo A 8.6", "Gestión de la capacidad", "Monitorear y ajustar el uso de recursos según la capacidad requerida.", "VIGENTE"),
    ("ISO-A.8.7", "ISO27001", "Anexo A 8.7", "Protección contra malware", "Protección contra software malicioso, incluido ransomware.", "VIGENTE"),
    ("ISO-A.8.8", "ISO27001", "Anexo A 8.8", "Gestión de vulnerabilidades técnicas", "Obtener información de vulnerabilidades, evaluar la exposición y tomar medidas.", "VIGENTE"),
    ("ISO-A.8.9", "ISO27001", "Anexo A 8.9", "Gestión de la configuración", "Establecer, documentar, implantar, monitorear y revisar configuraciones seguras.", "VIGENTE"),
    ("ISO-A.8.11", "ISO27001", "Anexo A 8.11", "Enmascaramiento de datos", "Enmascarar datos según la política de control de acceso y los requisitos legales.", "VIGENTE"),
    ("ISO-A.8.13", "ISO27001", "Anexo A 8.13", "Respaldo de la información", "Copias de respaldo mantenidas y probadas regularmente según la política acordada.", "VIGENTE"),
    ("ISO-A.8.15", "ISO27001", "Anexo A 8.15", "Registro de eventos", "Producir, almacenar, proteger y analizar registros de actividades, excepciones y fallas.", "VIGENTE"),
    ("ISO-A.8.16", "ISO27001", "Anexo A 8.16", "Actividades de monitoreo", "Monitorear redes, sistemas y aplicaciones para detectar comportamientos anómalos.", "VIGENTE"),
    ("ISO-A.8.20", "ISO27001", "Anexo A 8.20", "Seguridad de redes", "Proteger las redes y dispositivos de red, y la información en sistemas y aplicaciones.", "VIGENTE"),
    ("ISO-A.8.24", "ISO27001", "Anexo A 8.24", "Uso de criptografía", "Reglas para el uso efectivo de la criptografía, incluida la gestión de llaves.", "VIGENTE"),
    ("ISO-A.8.25", "ISO27001", "Anexo A 8.25", "Ciclo de vida de desarrollo seguro", "Reglas para el desarrollo seguro de software y sistemas.", "VIGENTE"),
    ("ISO-A.8.28", "ISO27001", "Anexo A 8.28", "Codificación segura", "Principios de codificación segura aplicados al desarrollo de software.", "VIGENTE"),
    ("ISO-A.8.29", "ISO27001", "Anexo A 8.29", "Pruebas de seguridad en desarrollo y aceptación", "Procesos de pruebas de seguridad definidos e implantados en el ciclo de desarrollo.", "VIGENTE"),
    ("ISO-A.8.31", "ISO27001", "Anexo A 8.31", "Separación de ambientes", "Separar y proteger los ambientes de desarrollo, pruebas y producción.", "VIGENTE"),
    ("ISO-A.8.32", "ISO27001", "Anexo A 8.32", "Gestión de cambios", "Los cambios en las instalaciones y sistemas se someten a procedimientos de gestión de cambios.", "VIGENTE"),
    ("ISO-A.8.33", "ISO27001", "Anexo A 8.33", "Información de prueba", "Seleccionar, proteger y gestionar adecuadamente la información de prueba.", "VIGENTE"),
    ("COBIT-DSS04", "COBIT", "DSS04", "Gestionar la continuidad", "Plan de continuidad del negocio y de TI, con pruebas periódicas.", "VIGENTE"),
    ("COBIT-DSS04.07", "COBIT", "DSS04.07", "Gestionar los respaldos", "Respaldos de sistemas, aplicaciones y datos según los requisitos de negocio.", "VIGENTE"),
    ("COBIT-DSS05.02", "COBIT", "DSS05.02", "Gestionar la seguridad de la red y las conexiones", "Medidas de seguridad para proteger la información en todos los métodos de conexión.", "VIGENTE"),
    ("COBIT-DSS05.04", "COBIT", "DSS05.04", "Gestionar la identidad y el acceso lógico", "Los usuarios tienen derechos de acceso según sus necesidades de negocio.", "VIGENTE"),
    ("COBIT-DSS05.07", "COBIT", "DSS05.07", "Gestionar la vigilancia de la infraestructura", "Registro y monitoreo de eventos de seguridad.", "VIGENTE"),
    ("COBIT-DSS06.02", "COBIT", "DSS06.02", "Controlar el procesamiento de la información", "Integridad, exactitud y validez del procesamiento de las transacciones.", "VIGENTE"),
    ("COBIT-BAI06", "COBIT", "BAI06", "Gestionar los cambios de TI", "Cambios autorizados, probados y documentados de forma controlada.", "VIGENTE"),
    ("COBIT-BAI07", "COBIT", "BAI07", "Gestionar la aceptación y la transición del cambio", "Aceptación formal por el negocio y transición controlada a producción.", "VIGENTE"),
    ("COBIT-MEA03", "COBIT", "MEA03", "Gestionar el cumplimiento de requisitos externos", "Cumplimiento de leyes, regulaciones y requisitos contractuales.", "VIGENTE"),
    ("VE-CRBV-28", "LEY_VE", "Constitución, art. 28", "Habeas data", "Derecho de toda persona a acceder a sus datos y a exigir su protección, actualización o rectificación. Venezuela no tiene una ley general de protección de datos.", "VIGENTE"),
    ("VE-LAA", "LEY_VE", "Ley de la Actividad Aseguradora", "Control interno de la actividad aseguradora", "Obligaciones de control interno, registro y supervisión de las empresas de seguros.", "POR_VALIDAR"),
    ("VE-LMDFE", "LEY_VE", "Decreto-Ley de Mensajes de Datos y Firmas Electrónicas", "Eficacia de mensajes de datos y firma electrónica", "Valor probatorio de los mensajes de datos y requisitos de la firma electrónica certificada (SUSCERTE).", "VIGENTE"),
    ("VE-LEDI", "LEY_VE", "Ley Especial contra los Delitos Informáticos", "Delitos contra sistemas de información", "Tipifica el acceso indebido, el sabotaje y la violación de la privacidad de datos.", "VIGENTE"),
    ("VE-INFOGOB", "LEY_VE", "Ley de Infogobierno", "Seguridad de la información en el uso de TIC", "Principios de seguridad e interoperabilidad de las tecnologías de información.", "VIGENTE"),
    ("VE-LOCDOFT", "LEY_VE", "Ley Orgánica contra la Delincuencia Organizada y Financiamiento al Terrorismo", "Prevención LC/FT/FPADM", "Deberes de prevención y reporte de los sujetos obligados.", "VIGENTE"),
    ("SUDEASEG-ELECTRONICO", "SUDEASEG", "Normas de trámites y procedimientos por medios electrónicos (G.O. Ext. 6.835 del 03/09/2024)", "Medios electrónicos y seguridad de la información", "Define la seguridad de la información (confidencialidad, integridad, privacidad y disponibilidad) en los trámites electrónicos.", "VIGENTE"),
    ("SUDEASEG-LCFT", "SUDEASEG", "Providencia SAA-01-0536-2024", "Administración de riesgos LC/FT/FPADM", "Sistema integral de administración de riesgos de legitimación de capitales.", "VIGENTE"),
    ("SUDEASEG-TI", "SUDEASEG", "Normas SUDEASEG sobre tecnología de la información (según matriz de Contraloría)", "Pistas de auditoría inalterables", "Mecanismos de audit trail que registren el ciclo de vida completo de cada transacción.", "POR_VALIDAR"),
    ("SUDEASEG-CAMBIOS", "SUDEASEG", "Normas sobre control de cambios en sistemas aplicativos (según matriz de Contraloría)", "Control de cambios", "Ambientes segregados QA/producción con autorización formal (RFC) y pruebas.", "POR_VALIDAR"),
    ("SUDEASEG-CONTINUIDAD", "SUDEASEG", "Lineamientos de BCP/DRP y riesgo operacional (según matriz de Contraloría)", "Continuidad de los sistemas misionales", "Respaldos periódicos y pruebas formales de recuperación ante desastres.", "POR_VALIDAR"),
    ("SUDEASEG-RESERVAS", "SUDEASEG", "Providencias sobre notas técnicas y reservas técnicas", "Parámetros actuariales", "El software aplica fielmente las fórmulas actuariales de las notas técnicas aprobadas.", "POR_VALIDAR"),
    ("SUDEASEG-CONTABLE", "SUDEASEG", "Normativa contable SUDEASEG y presentación de balances", "Integridad financiera", "Cuadre, conciliación periódica y prohibición de asientos manuales no justificados.", "POR_VALIDAR"),
    ("SUDEASEG-INTERMEDIARIOS", "SUDEASEG", "Régimen de autorización de intermediarios de seguros", "Intermediarios autorizados", "Solo se opera con intermediarios cuya autorización esté vigente.", "POR_VALIDAR"),
]

BY_CODE = {n[0]: n for n in NORMS}


def as_dicts(rows=None) -> list[dict]:
    keys = ("code", "source", "reference", "title", "summary", "status")
    return [dict(zip(keys, r)) for r in (rows or NORMS)]


def cite(codes, catalog: dict | None = None) -> str:
    """Texto del criterio a partir de los códigos citados por el control (agrupado por fuente)."""
    catalog = catalog or {n["code"]: n for n in as_dicts()}
    parts: dict[str, list[str]] = {}
    pending = False
    for c in codes or []:
        n = catalog.get(c)
        if not n:
            continue
        label = SOURCES.get(n["source"], n["source"])
        ref = n["reference"] if n["source"] in ("LEY_VE", "SUDEASEG") else n["reference"].replace("Anexo A ", "")
        parts.setdefault(label, []).append(f"{ref} ({n['title'].lower()})")
        pending = pending or n.get("status") == "POR_VALIDAR"
    if not parts:
        return ""
    text = "; ".join(f"{src}: {', '.join(refs)}" for src, refs in parts.items()) + "."
    if pending:
        text += " Las referencias SUDEASEG marcadas como por validar deben confirmarse con el área legal."
    return text
