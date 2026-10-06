!/bin/bash

# SICAS - Ejecuta las consultas RBAC y guarda TODO el resultado en un archivo.
# Ejecutar desde:
# /Users/macbook/Documents/Proyectos/SICAS

set -e

OUTPUT="resultado_permisos_sicas.txt"

echo "Generando $OUTPUT..."

{
    echo "============================================================"
    echo "SICAS - REPORTE DE PERMISOS RBAC"
    echo "Fecha:"
    date
    echo "============================================================"
    echo

    echo "============================================================"
    echo "1. CATÁLOGO COMPLETO DE PERMISOS"
    echo "============================================================"

    docker compose -f infra/docker/docker-compose.yml exec -T db \
    psql -U postgres -d contraloria \
    -c "
    SELECT id, code, description
    FROM iam.permissions
    ORDER BY code;
    "

    echo
    echo "============================================================"
    echo "2. PERMISOS ASIGNADOS A CADA ROL"
    echo "============================================================"

    docker compose -f infra/docker/docker-compose.yml exec -T db \
    psql -U postgres -d contraloria \
    -c "
    SELECT
        r.code AS rol,
        p.code AS permiso
    FROM iam.roles r
    JOIN iam.role_permissions rp ON rp.role_id = r.id
    JOIN iam.permissions p ON p.id = rp.permission_id
    ORDER BY r.code, p.code;
    "

    echo
    echo "============================================================"
    echo "FIN DEL REPORTE"
    echo "============================================================"
} > "$OUTPUT"

echo
echo "=============================================="
echo "REPORTE GENERADO CORRECTAMENTE"
echo "=============================================="
echo "Archivo: $OUTPUT"
echo "Ubicación: $(pwd)/$OUTPUT"
echo
echo "Puedes abrirlo con:"
echo "open \"$OUTPUT\""
echo "=============================================="
