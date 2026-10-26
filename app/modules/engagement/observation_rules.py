"""Redacción de observaciones de Auditoría de Sistemas a partir de la cédula (lógica pura, sin servicios externos).

Cada control respondido que representa una brecha produce una observación con siete campos:
riesgo, título, condición, criterio, causa, efecto/riesgo y recomendación. El texto se arma con
las respuestas de la fila (existencia, soporte documental, evidencia y observación del auditor)
y con un catálogo de dominios de control alineado a ISO/IEC 27001:2022, COBIT 2019 y CIS
Controls v8. El resultado es reproducible: la misma cédula produce siempre las mismas
observaciones, y el auditor las revisa y ajusta antes del informe.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

RISK_ORDER = ("BAJO", "MEDIO", "ALTO")


@dataclass(frozen=True)
class Domain:
    key: str
    label: str
    keywords: tuple[str, ...]
    criteria: str
    cause: str
    effect: str
    recommendation: str
    test: str
    critical: bool = False


DOMAINS: tuple[Domain, ...] = (
    Domain(
        "accesos", "gestión de accesos e identidades",
        ("acceso", "cuentas de usuario", "alta de usuario", "baja de usuario", "usuarios privilegiados", "usuarios genericos",
         "contrasena", "password", "privilegi", "autentic", "credencial", "perfiles de", "roles y", "segregacion de funciones",
         "mfa", "doble factor", "sesion"),
        "ISO/IEC 27001:2022 Anexo A 5.15 (control de acceso), 5.16 (gestión de identidades), 5.18 (derechos de acceso) y 8.5 "
        "(autenticación segura); COBIT 2019 DSS05.04 (gestionar la identidad y el acceso lógico); CIS Controls v8, controles 5 y 6.",
        "No existe un procedimiento formal y aprobado de altas, bajas y revisión periódica de accesos, ni una herramienta que "
        "centralice las identidades; la asignación de privilegios depende de solicitudes informales y no se revisa de forma recurrente.",
        "Cuentas activas de personal desvinculado, privilegios excesivos o contraseñas débiles permiten el acceso no autorizado a "
        "sistemas y datos de clientes y pólizas, con riesgo de fraude interno, fuga de información, despliegue de ransomware con "
        "credenciales comprometidas y sanciones del ente regulador por fallas en la protección de datos.",
        "Formalizar y aprobar la política y el procedimiento de gestión de accesos (alta, modificación, baja y revisión trimestral "
        "de privilegios), implementar autenticación multifactor en accesos remotos y administrativos, depurar las cuentas no "
        "justificadas y conservar evidencia de cada revisión.",
        "Seleccionar una muestra de usuarios activos y privilegiados, cotejarla con la nómina vigente y con las solicitudes "
        "aprobadas, y verificar la última revisión periódica de accesos y la configuración de contraseñas y MFA.",
        critical=True,
    ),
    Domain(
        "respaldos", "respaldo y recuperación de la información",
        ("respaldo", "backup", "copia de seguridad", "copias de seguridad", "restaur", "recuperacion de datos"),
        "ISO/IEC 27001:2022 Anexo A 8.13 (respaldo de la información); COBIT 2019 DSS04.07 (gestionar los respaldos); "
        "CIS Controls v8, control 11 (recuperación de datos).",
        "La ejecución de respaldos no está definida en un procedimiento con frecuencia, retención, custodia fuera de sitio y "
        "pruebas de restauración; no hay un responsable asignado ni monitoreo de los resultados de las tareas programadas.",
        "Ante un ataque de ransomware, una falla de hardware o un borrado accidental, la organización podría no recuperar "
        "información crítica (pólizas, siniestros, contabilidad), con interrupción prolongada de operaciones, pérdida de datos "
        "irrecuperable y exposición a multas por incumplimiento de las obligaciones de conservación de registros.",
        "Documentar y aprobar la política de respaldos (alcance, frecuencia, retención, copias inmutables o fuera de línea), "
        "asignar responsables, monitorear cada ejecución y realizar pruebas de restauración al menos trimestrales con acta firmada.",
        "Revisar la bitácora de respaldos del último período, verificar la existencia de copias fuera de sitio o inmutables y "
        "presenciar una restauración de prueba de un sistema crítico.",
        critical=True,
    ),
    Domain(
        "cambios", "gestión de cambios y desarrollo",
        ("cambio", "desarrollo", "pase a produccion", "despliegue", "release", "codigo fuente", "ambiente de prueba", "ambientes", "personaliz", "customiz"),
        "ISO/IEC 27001:2022 Anexo A 8.25 (ciclo de vida de desarrollo seguro), 8.31 (separación de ambientes) y 8.32 "
        "(gestión de cambios); COBIT 2019 BAI06 (gestionar los cambios de TI); CIS Controls v8, control 16.",
        "No existe un procedimiento formal de gestión de cambios con solicitud, evaluación de impacto, aprobación, pruebas y "
        "plan de reversión; los cambios se aplican directamente sin segregación entre desarrollo, pruebas y producción.",
        "Cambios no autorizados o no probados pueden interrumpir los sistemas centrales, introducir errores en el cálculo de "
        "primas y reservas, abrir puertas traseras o facilitar fraudes internos sin trazabilidad del responsable.",
        "Implementar un procedimiento de gestión de cambios con comité o aprobador designado, registro de cada solicitud, "
        "pruebas documentadas, segregación de ambientes y plan de reversión, y conservar la evidencia de cada pase a producción.",
        "Tomar una muestra de pases a producción del período y verificar solicitud, aprobación, pruebas, plan de reversión y "
        "que quien desarrolló no fue quien aprobó o desplegó el cambio.",
    ),
    Domain(
        "registros", "registro y monitoreo de eventos",
        ("log ", "logs", "bitacora", "registro de eventos", "monitoreo", "monitorizacion", "auditoria de eventos", "siem", "alerta",
         "trazabilidad", "pista de auditoria", "pistas de auditoria", "audit trail", "registro de auditoria"),
        "ISO/IEC 27001:2022 Anexo A 8.15 (registro de eventos) y 8.16 (actividades de monitoreo); COBIT 2019 DSS05.07 "
        "(gestionar la supervisión de la infraestructura); CIS Controls v8, control 8.",
        "No se ha definido qué eventos deben registrarse, cuánto tiempo se conservan ni quién los revisa; no se dispone de una "
        "herramienta de centralización y correlación de registros.",
        "Un intruso o un usuario interno podría actuar sin ser detectado y borrar sus rastros; la ausencia de registros impide "
        "la investigación forense de incidentes, de fraudes y la atención de requerimientos legales o regulatorios.",
        "Definir y aprobar la política de registro y monitoreo (eventos mínimos, retención, protección contra alteración), "
        "centralizar los registros de sistemas críticos y establecer revisiones periódicas con alertas sobre eventos de riesgo.",
        "Solicitar los registros de un sistema crítico para una fecha determinada, verificar su integridad, retención y la "
        "evidencia de revisión o de alertas atendidas.",
    ),
    Domain(
        "vulnerabilidades", "gestión de parches y vulnerabilidades",
        ("parche", "actualizacion", "vulnerab", "escaneo", "pentest", "prueba de penetracion", "obsolet", "fin de soporte"),
        "ISO/IEC 27001:2022 Anexo A 8.8 (gestión de vulnerabilidades técnicas); COBIT 2019 DSS05.01 (protección contra "
        "software malicioso) y BAI03; CIS Controls v8, control 7 (gestión continua de vulnerabilidades).",
        "No existe un proceso formal de inventario de vulnerabilidades, priorización y aplicación de parches con plazos "
        "definidos; las actualizaciones se aplican de forma reactiva y sin registro.",
        "Vulnerabilidades conocidas y sin corregir son el vector habitual de ransomware y de intrusiones remotas; su explotación "
        "puede paralizar la operación, cifrar o exfiltrar datos de asegurados y derivar en pérdidas económicas y reputacionales.",
        "Implementar un programa de gestión de vulnerabilidades con escaneos periódicos, criterios de criticidad, plazos máximos "
        "de corrección y reportes a la gerencia, y reemplazar o aislar los sistemas sin soporte del fabricante.",
        "Revisar el último escaneo de vulnerabilidades y el estado de parches de una muestra de servidores y estaciones, "
        "comparando contra los boletines del fabricante.",
        critical=True,
    ),
    Domain(
        "malware", "protección contra código malicioso",
        ("antivirus", "malware", "edr", "endpoint", "virus", "ransomware"),
        "ISO/IEC 27001:2022 Anexo A 8.7 (protección contra malware); COBIT 2019 DSS05.01; CIS Controls v8, control 10 (defensas contra malware).",
        "La protección contra malware no está gestionada de forma centralizada ni cubierta por un procedimiento que asegure su "
        "instalación, actualización y atención de alertas en todos los equipos.",
        "Equipos sin protección o con firmas desactualizadas facilitan la infección por ransomware y troyanos bancarios, con "
        "cifrado de información, robo de credenciales y propagación lateral en la red corporativa.",
        "Desplegar una solución antimalware/EDR administrada centralmente en todos los equipos y servidores, monitorear su "
        "cobertura y actualización, y documentar el procedimiento de atención de alertas.",
        "Verificar en la consola central la cobertura y la fecha de actualización de firmas en una muestra de equipos y la "
        "atención de las alertas recientes.",
        critical=True,
    ),
    Domain(
        "redes", "seguridad de redes y telecomunicaciones",
        ("firewall", "cortafuego", "red ", "redes", "vpn", "wifi", "wi-fi", "inalambric", "segment", "switch", "router", "telecom", "perimetr", "puerto"),
        "ISO/IEC 27001:2022 Anexo A 8.20 (seguridad de redes), 8.21 (seguridad de los servicios de red) y 8.22 (segregación "
        "de redes); COBIT 2019 DSS05.02; CIS Controls v8, controles 12 y 13.",
        "La configuración de la red no está documentada ni sometida a revisiones periódicas de reglas; no existe segmentación "
        "formal entre redes de usuarios, servidores y terceros.",
        "Una red plana o con reglas permisivas permite que un atacante que comprometa un equipo se desplace hasta los servidores "
        "críticos, exfiltre información o despliegue ransomware en toda la organización.",
        "Documentar la arquitectura de red, segmentar las zonas críticas, revisar y depurar semestralmente las reglas del firewall "
        "con aprobación formal, y asegurar los accesos remotos mediante VPN con autenticación multifactor.",
        "Obtener la configuración vigente del firewall, verificar las reglas de una muestra contra su justificación aprobada y "
        "comprobar la segmentación entre redes de usuarios y servidores.",
    ),
    Domain(
        "cifrado", "cifrado y protección de datos",
        ("cifrad", "encript", "certificado", "ssl", "tls", "datos personales", "confidencial", "clasificacion de la informacion"),
        "ISO/IEC 27001:2022 Anexo A 5.12 (clasificación de la información), 5.34 (privacidad y protección de datos personales) "
        "y 8.24 (uso de criptografía); COBIT 2019 DSS05.03; CIS Controls v8, control 3 (protección de datos).",
        "No se ha clasificado la información ni definido qué datos deben cifrarse en reposo y en tránsito; no existe gestión del "
        "ciclo de vida de llaves y certificados.",
        "La pérdida o interceptación de información no cifrada (bases de datos, respaldos, equipos portátiles) expone datos de "
        "asegurados y de la operación, con responsabilidad legal, sanciones regulatorias y daño reputacional.",
        "Aprobar la política de clasificación y cifrado de la información, cifrar los datos sensibles en reposo y en tránsito, y "
        "llevar un inventario de certificados y llaves con responsables y fechas de vencimiento.",
        "Verificar en una muestra de sistemas y respaldos que los datos sensibles se almacenan y transmiten cifrados y revisar la "
        "vigencia de los certificados publicados.",
    ),
    Domain(
        "continuidad", "continuidad del negocio y recuperación ante desastres",
        ("continuidad", "contingencia", "desastre", "drp", "bcp", "alta disponibilidad", "sitio alterno", "recuperacion ante",
         "failover", "rto", "rpo", "downtime"),
        "ISO/IEC 27001:2022 Anexo A 5.29 (seguridad durante una disrupción) y 5.30 (preparación de las TIC para la continuidad); "
        "COBIT 2019 DSS04 (gestionar la continuidad); CIS Controls v8, control 11.",
        "No existe un plan de continuidad y recuperación de TI aprobado, con tiempos objetivo de recuperación, responsables y "
        "pruebas periódicas.",
        "Ante una contingencia mayor (ransomware, falla del centro de datos, desastre natural) la organización no podría "
        "restablecer a tiempo la emisión de pólizas y el pago de siniestros, con pérdidas económicas e incumplimientos regulatorios.",
        "Elaborar y aprobar el plan de recuperación de TI con análisis de impacto, RTO/RPO por sistema y roles definidos, y "
        "ejecutar pruebas al menos anuales con informe de resultados y acciones de mejora.",
        "Revisar el plan vigente, su aprobación y el informe de la última prueba, verificando que los tiempos alcanzados cumplen "
        "los objetivos definidos.",
        critical=True,
    ),
    Domain(
        "incidentes", "gestión de incidentes de seguridad",
        ("incidente", "brecha", "respuesta a", "forense", "csirt"),
        "ISO/IEC 27001:2022 Anexo A 5.24 a 5.28 (gestión de incidentes de seguridad de la información); COBIT 2019 DSS02; "
        "CIS Controls v8, control 17.",
        "No se ha formalizado un procedimiento de reporte, clasificación, contención y lecciones aprendidas de incidentes, ni un "
        "equipo responsable con roles definidos.",
        "La respuesta improvisada ante un incidente amplía su impacto: mayor tiempo de indisponibilidad, pérdida de evidencia, "
        "propagación del ataque y notificaciones tardías a clientes y reguladores.",
        "Aprobar el procedimiento de gestión de incidentes con matriz de escalamiento, registro único de incidentes, plantillas "
        "de comunicación y ejercicios periódicos de simulación.",
        "Revisar el registro de incidentes del período y una muestra de casos cerrados, verificando clasificación, tiempos de "
        "atención, evidencias y lecciones aprendidas.",
    ),
    Domain(
        "activos", "inventario de activos y licenciamiento",
        ("inventario", "activo", "licencia", "licenciamiento", "hardware", "software instalado", "equipo de computo", "equipos"),
        "ISO/IEC 27001:2022 Anexo A 5.9 (inventario de información y otros activos) y 5.32 (derechos de propiedad intelectual); "
        "COBIT 2019 BAI09 (gestionar los activos); CIS Controls v8, controles 1 y 2.",
        "No existe un inventario actualizado y conciliado de hardware y software con responsables asignados, ni un control del "
        "licenciamiento instalado.",
        "Sin inventario no es posible proteger, parchar ni recuperar los activos; equipos no controlados se convierten en puntos "
        "de entrada para atacantes y el software sin licencia expone a sanciones legales.",
        "Implementar un inventario automatizado de hardware y software, conciliarlo periódicamente con los registros contables y "
        "de licencias, y asignar un custodio a cada activo.",
        "Seleccionar una muestra de equipos físicos y verificar su registro en el inventario, su custodio y el licenciamiento del "
        "software instalado.",
    ),
    Domain(
        "terceros", "gestión de proveedores y servicios de terceros",
        ("proveedor", "tercero", "outsourcing", "contrato", "nube", "cloud", "acuerdo de nivel", "sla", "escrow", "custodia", "fabricante"),
        "ISO/IEC 27001:2022 Anexo A 5.19 a 5.23 (seguridad en las relaciones con proveedores y servicios en la nube); COBIT "
        "2019 APO10 (gestionar los proveedores); CIS Controls v8, control 15.",
        "Los contratos con proveedores de TI no incluyen cláusulas de seguridad, confidencialidad y niveles de servicio, ni se "
        "evalúa periódicamente su cumplimiento.",
        "Un proveedor con accesos o datos de la organización y controles débiles puede originar fugas de información, "
        "interrupciones del servicio o ataques a la cadena de suministro sin posibilidad de exigir responsabilidades.",
        "Incorporar cláusulas de seguridad, confidencialidad, auditoría y niveles de servicio en los contratos, mantener un "
        "registro de proveedores críticos y evaluar su desempeño y riesgos al menos una vez al año.",
        "Revisar los contratos de una muestra de proveedores críticos y la evidencia de la última evaluación de su cumplimiento.",
    ),
    Domain(
        "configuracion", "configuración segura de servidores y bases de datos",
        ("servidor", "base de datos", "bases de datos", "configuracion", "hardening", "sistema operativo", "dba", "motor"),
        "ISO/IEC 27001:2022 Anexo A 8.9 (gestión de la configuración) y 8.3 (restricción del acceso a la información); COBIT "
        "2019 BAI10 (gestionar la configuración); CIS Controls v8, control 4 y CIS Benchmarks del fabricante.",
        "No existen líneas base de configuración segura aprobadas para servidores y bases de datos, ni revisiones periódicas "
        "que detecten desviaciones.",
        "Configuraciones por defecto, servicios innecesarios o cuentas genéricas activas facilitan la intrusión y la alteración "
        "directa de datos de pólizas, siniestros o contabilidad, con riesgo de fraude y pérdida de integridad.",
        "Definir y aplicar líneas base de configuración segura según los CIS Benchmarks, eliminar cuentas y servicios "
        "innecesarios y verificar semestralmente el cumplimiento con herramientas automatizadas.",
        "Comparar la configuración de una muestra de servidores y bases de datos contra la línea base aprobada y verificar las "
        "cuentas con privilegios administrativos.",
    ),
    Domain(
        "concienciacion", "concienciación y capacitación en seguridad",
        ("capacitacion", "concienciacion", "concientizacion", " formacion", "entrenamiento", "phishing", "simulacro"),
        "ISO/IEC 27001:2022 Anexo A 6.3 (concienciación, educación y formación); COBIT 2019 APO07.03; CIS Controls v8, control 14.",
        "No existe un programa anual de concienciación en seguridad con contenidos, cobertura y medición de resultados.",
        "El personal no capacitado es el principal vector de phishing y robo de credenciales, punto de partida frecuente de "
        "ransomware y fraudes por suplantación.",
        "Implementar un programa anual de concienciación con módulos obligatorios, simulaciones de phishing y medición de "
        "resultados reportada a la gerencia.",
        "Verificar el programa vigente, la lista de asistencia o finalización del último ciclo y los resultados de simulaciones.",
    ),
    Domain(
        "ciclo_vida", "ciclo de vida y obsolescencia tecnológica",
        ("fin de vida", "eol", "eos", "fin de soporte", "soporte tecnico", "roadmap", "migracion", "obsolet", "actualizacion o migracion",
         "presupuesto", "version del erp", "version actual"),
        "ISO/IEC 27001:2022 Anexo A 8.8 (gestión de vulnerabilidades técnicas) y 5.37; COBIT 2019 APO02 (estrategia), APO04 "
        "(innovación) y BAI03 (soluciones); CIS Controls v8, control 2.2 (software con soporte del fabricante).",
        "La gerencia de TI no ha formalizado un plan de ciclo de vida de la plataforma con fechas de fin de soporte, "
        "presupuesto y responsables, por lo que la renovación tecnológica depende de decisiones reactivas.",
        "Operar sistemas sin soporte del fabricante impide recibir parches de seguridad: vulnerabilidades conocidas quedan "
        "abiertas para ransomware y fraudes, y una falla mayor podría no tener asistencia técnica, paralizando la operación.",
        "Documentar y aprobar el roadmap de actualización o migración con fechas de fin de soporte del fabricante, presupuesto "
        "asignado y responsables, y definir controles compensatorios mientras se ejecuta.",
        "Verificar con el fabricante las fechas de EOL/EOS de la versión en producción y revisar el roadmap aprobado y su presupuesto.",
    ),
    Domain(
        "riesgos", "gestión de riesgos tecnológicos y criticidad",
        ("riesgo", "matriz", "criticidad", "bia", "impacto al negocio", "clasificacion formal"),
        "ISO/IEC 27001:2022 cláusulas 6.1.2 (evaluación de riesgos) y 8.2; ISO/IEC 27005; COBIT 2019 APO12 (gestionar el "
        "riesgo) y EDM03.",
        "No existe una metodología formal de evaluación de riesgos tecnológicos ni un análisis de impacto al negocio que "
        "clasifique la criticidad de los sistemas.",
        "Sin conocer la criticidad de cada sistema, los recursos de protección y recuperación se asignan sin prioridad: un "
        "incidente sobre un sistema crítico podría tener un impacto financiero y regulatorio no previsto.",
        "Aprobar la metodología de gestión de riesgos tecnológicos, realizar el BIA, registrar la criticidad de cada sistema en "
        "la matriz de riesgos y actualizarla al menos una vez al año.",
        "Revisar la matriz de riesgos y el BIA vigentes, su aprobación y la inclusión del sistema auditado con su criticidad.",
    ),
    Domain(
        "gobierno", "gobierno y políticas de seguridad de la información",
        ("politica", "procedimiento", "manual", "norma", "gobierno", "comite", "responsable", "aprobad", "lineamiento", "estrategia", "plan "),
        "ISO/IEC 27001:2022 cláusulas 5.2 (política) y 7.5 (información documentada), Anexo A 5.1 (políticas de seguridad) y "
        "5.37 (procedimientos operativos documentados); COBIT 2019 APO01 y EDM01.",
        "La unidad no ha formalizado el documento rector del control ni definido responsables de su elaboración, aprobación, "
        "divulgación y revisión periódica; la práctica descansa en el conocimiento de personas clave.",
        "Sin lineamientos aprobados los controles se aplican de forma inconsistente, no pueden exigirse ni auditarse y dependen "
        "de personas específicas, lo que aumenta la probabilidad de errores, fraudes y observaciones del ente regulador.",
        "Elaborar, aprobar por la instancia competente y divulgar el documento formal del control, asignar su responsable, "
        "establecer su revisión al menos anual y conservar la evidencia de su aplicación.",
        "Verificar la existencia del documento aprobado y vigente, su divulgación al personal y una muestra de evidencias de su aplicación.",
    ),
)

DEFAULT_DOMAIN = Domain(
    "general", "tecnología de la información", (),
    "ISO/IEC 27001:2022 cláusula 6.1 (acciones para tratar riesgos) y controles aplicables del Anexo A; COBIT 2019 DSS05 "
    "(gestionar los servicios de seguridad); CIS Controls v8.",
    "El control no ha sido formalizado mediante un proceso documentado, con responsables, herramientas de soporte y "
    "supervisión de la gerencia de TI.",
    "La ausencia o debilidad del control aumenta la exposición de los sistemas y de la información de la aseguradora a "
    "accesos no autorizados, interrupciones del servicio, fraudes y sanciones regulatorias.",
    "Diseñar, documentar y aprobar el control, asignar su responsable, implementarlo con las herramientas necesarias y "
    "conservar evidencia periódica de su ejecución para el seguimiento de auditoría.",
    "Verificar en sitio la ejecución del control con evidencia del período auditado y entrevistar al responsable.",
)

CONTROL_LABEL = {"SI": "existe", "NO": "no existe"}
EVIDENCE_LABEL = {"ACTUALIZADO": "actualizada", "DESACTUALIZADO": "desactualizada", "INEXISTENTE": "inexistente"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _answers(result: dict) -> tuple[str, str, str]:
    """Existencia, soporte documental y evidencia normalizados (admite 'Sí', 'si', etc.)."""
    return tuple(_norm(result.get(k) or "").strip().upper() for k in ("control", "documental", "evidencia"))


def domain_for(section: str, question: str) -> Domain:
    """Dominio con más coincidencias en la pregunta (la sección solo desempata o suple); en empate, el del catálogo."""
    q, s = f" {_norm(question)} ", f" {_norm(section)} "
    best, best_score = DEFAULT_DOMAIN, 0
    for d in DOMAINS:
        score = 2 * sum(1 for k in d.keywords if k in q) + sum(1 for k in d.keywords if k in s)
        if d.key == "gobierno":
            score /= 2   # dominio genérico: solo gana si no hay uno específico
        if score > best_score:
            best, best_score = d, score
    return best


def gap_of(result: dict) -> str | None:
    """Tipo de brecha de la fila, o None si el control está soportado (SI, documentado y evidencia actualizada)."""
    control, doc, evidence = _answers(result)
    if control not in ("SI", "NO"):
        return None                       # sin responder: no se presume brecha
    if control == "NO":
        return "INEXISTENTE"
    if doc != "SI":
        return "SIN_SOPORTE"
    if evidence == "INEXISTENTE":
        return "SIN_EVIDENCIA"
    if evidence == "DESACTUALIZADO":
        return "DESACTUALIZADO"
    return None


BASE_RISK = {"INEXISTENTE": "ALTO", "SIN_SOPORTE": "MEDIO", "SIN_EVIDENCIA": "MEDIO", "DESACTUALIZADO": "BAJO"}
TITLE_PREFIX = {
    "INEXISTENTE": "Ausencia de control de",
    "SIN_SOPORTE": "Control de {} sin soporte documental",
    "SIN_EVIDENCIA": "Control de {} sin evidencia de ejecución",
    "DESACTUALIZADO": "Documentación desactualizada del control de",
}


def risk_for(gap: str, domain: Domain, weight) -> str:
    """Riesgo por tipo de brecha, alineado con los indicadores de la cédula.

    ALTO: el control no existe. MEDIO: existe sin soporte documental o sin evidencia. BAJO: evidencia
    desactualizada. Un control de peso 3 (crítico) sube un nivel; un dominio crítico (accesos,
    respaldos, parches, malware, continuidad) eleva a MEDIO la evidencia desactualizada.
    """
    level = RISK_ORDER.index(BASE_RISK[gap])
    try:
        heavy = int(weight or 1) >= 3
    except (TypeError, ValueError):
        heavy = False
    if heavy:
        level = min(level + 1, len(RISK_ORDER) - 1)
    elif domain.critical and level == 0:
        level = 1
    return RISK_ORDER[level]


def _sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if not text or text.endswith((".", "?", "!")) else text + "."


def _short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".:;")
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def draft(criterion: dict, result: dict, observation: str | None = None) -> dict | None:
    """Observación de siete campos para una fila de la cédula, o None si no hay brecha."""
    gap = gap_of(result or {})
    if gap is None:
        return None
    code = criterion.get("code") or ""
    question = criterion.get("text") or criterion.get("question") or code
    section = criterion.get("section") or ""
    dom = domain_for(section, question)
    control, doc, evidence = _answers(result)

    prefix = TITLE_PREFIX[gap]
    title = prefix.format(dom.label) if "{}" in prefix else f"{prefix} {dom.label}"
    title = f"{title} ({code})" if code else title

    found = {
        "INEXISTENTE": "la unidad indicó que el control no existe",
        "SIN_SOPORTE": "la unidad indicó que el control existe, pero no presentó soporte documental que lo respalde",
        "SIN_EVIDENCIA": "el control existe y está documentado, pero no se dispone de evidencia o entregable que demuestre su ejecución",
        "DESACTUALIZADO": "el control existe y está documentado, pero la evidencia disponible está desactualizada",
    }[gap]
    condition = (
        f"En el levantamiento de información{(' de la sección «' + section + '»') if section else ''}, para el control {code} "
        f"«{_short(question, 300)}», {found}. Respuestas registradas: existencia {CONTROL_LABEL.get(control, 'sin respuesta')}, "
        f"soporte documental {'sí' if doc == 'SI' else 'no'}, evidencia {EVIDENCE_LABEL.get(evidence, 'no indicada')}."
    )
    if observation and str(observation).strip():
        condition += f" Observación del auditor: {_sentence(observation)}"

    return {
        "risk": risk_for(gap, dom, criterion.get("weight")),
        "title": _short(title, 200),
        "condition": condition[:3000],
        "criteria": dom.criteria,
        "cause": dom.cause,
        "effect": dom.effect,
        "recommendation": dom.recommendation,
        "domain": dom.key,
        "gap": gap,
    }


def field_test_for(criterion: dict) -> str:
    """Procedimiento sugerido para la prueba de campo de un control documentado."""
    dom = domain_for(criterion.get("section") or "", criterion.get("text") or "")
    return dom.test
