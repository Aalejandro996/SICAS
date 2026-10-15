// SICAS — Dashboard privado del Contralor. Solo consume endpoints agregados de lectura.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl } = S;
  const METRIC_ORDER = ['AUDITS_TOTAL', 'AUDITS_IN_PROGRESS', 'AUDITS_CLOSED', 'AUDIT_COMPLETION_PCT',
    'OBSERVATIONS_TOTAL', 'HIGH_RISK_OBSERVATIONS', 'HIGH_RISK_SHARE_PCT', 'AVG_CLOSED_AUDIT_DAYS',
    'AVG_PHASE_HOURS', 'INGESTION_AVG_SECONDS', 'INGESTION_REJECTION_PCT'];
  const PERIODS = [['MENSUAL', 'Mensual'], ['TRIMESTRAL', 'Trimestral'], ['SEMESTRAL', 'Semestral'], ['ANUAL', 'Anual']];
  const fmt = (v, suffix = '') => v == null || v === '' ? '—' : `${Number(v).toLocaleString('es-VE', { maximumFractionDigits: 2 })}${suffix}`;
  const prettyRisk = (v) => ({ CRITICAL: 'Crítico', HIGH: 'Alto', MEDIUM: 'Medio', LOW: 'Bajo', UNSPECIFIED: 'Sin clasificar', OTHER: 'Otros / valor no estándar' })[v] || v;
  const queryString = (filters) => new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '' && v != null))).toString();
  const option = (value, label) => h('option', { value }, label);
  const panel = (title, child) => h('section', { class: 'panel contralor-panel' }, h('h3', null, title), child);
  const emptyText = (text) => h('p', { class: 'muted' }, text);

  function barList(entries, labelFn, valueFn, titleFn) {
    if (!entries.length) return emptyText('No hay registros para el período y los filtros seleccionados.');
    const max = Math.max(1, ...entries.map((row) => Number(valueFn(row) || 0)));
    return h('div', { class: 'ctl-bar-list' }, entries.map((row) => {
      const value = Number(valueFn(row) || 0);
      return h('div', { class: 'ctl-bar-row', title: titleFn ? titleFn(row) : `${labelFn(row)}: ${value}` },
        h('div', { class: 'ctl-bar-label' }, labelFn(row)),
        h('div', { class: 'ctl-bar-track', role: 'img', 'aria-label': `${labelFn(row)}: ${value}` },
          h('div', { class: 'ctl-bar-value ctl-width-' + Math.max(0, Math.min(100, Math.round(value / max * 100))) })),
        h('div', { class: 'ctl-bar-number' }, fmt(value)));
    }));
  }

  function trendChart(entries) {
    if (!entries.length) return emptyText('No existen auditorías en los períodos seleccionados.');
    const max = Math.max(1, ...entries.map((r) => Math.max(Number(r.audits_total || 0), Number(r.observations_total || 0))));
    return h('div', { class: 'ctl-trend-chart' }, entries.map((r) => {
      const raw = r.period_start;
      const d = new Date(`${String(raw).slice(0, 10)}T12:00:00`);
      const label = Number.isNaN(d.getTime()) ? String(raw).slice(0, 10) : d.toLocaleDateString('es-VE', { year: '2-digit', month: 'short' });
      return h('div', { class: 'ctl-trend-col', title: `${label}: ${r.audits_total} auditorías, ${r.observations_total} observaciones` },
        h('div', { class: 'ctl-trend-bars' },
          h('div', { class: 'ctl-trend-audits ctl-height-' + Math.max(1, Math.min(100, Math.round(Number(r.audits_total || 0) / max * 100))) }),
          h('div', { class: 'ctl-trend-obs ctl-height-' + Math.max(1, Math.min(100, Math.round(Number(r.observations_total || 0) / max * 100))) })),
        h('div', { class: 'ctl-trend-label' }, label),
        h('div', { class: 'ctl-trend-value' }, `${r.audits_total} / ${r.observations_total}`));
    }));
  }

  function chartLegend() {
    return h('div', { class: 'ctl-legend' },
      h('span', null, h('i', { class: 'ctl-legend-audits' }), ' Auditorías creadas (cohorte)'),
      h('span', null, h('i', { class: 'ctl-legend-obs' }), ' Brechas creadas'));
  }

  S.pages.push({
    id: 'contralor-dashboard', title: 'Dashboard', perms: [
      'dashboard:contralor', 'dashboard:executive',
      'audit:financial_review', 'audit:systems_review'
    ],
    render: async (el) => {
      const isContralor = can('dashboard:contralor');
      const isGerencia = !isContralor && can('dashboard:executive');
      const lockedDomain = !isContralor && !isGerencia
        ? (can('audit:financial_review') ? 'FINANCIERA'
          : can('audit:systems_review') ? 'SISTEMAS' : null)
        : null;
      const isDomainHead = Boolean(lockedDomain);
      el.append(h('h2', null, 'Dashboard'),
        h('p', { class: 'muted' }, isDomainHead
          ? `Vista restringida al dominio ${lockedDomain}. Puede definir KPI individuales para los auditores de su dominio.`
          : 'Vista agregada. Las duraciones de fase son tiempos transcurridos y no equivalen a horas de trabajo activo del auditor.'));
      const options = await S.get('/analytics/contralor/options');
      if (!options) return;

      const start = h('input', { type: 'date' });
      const end = h('input', { type: 'date' });
      const unit = h('select', null, option('', 'Todas las unidades'), options.units.map((u) => option(String(u.id), `${u.code} — ${u.name}`)));
      const auditor = h('select', null, option('', 'Todos los auditores'), options.auditors.map((u) => option(u.id, u.name)));
      const domain = h('select', null, option('', 'Todos los dominios'), options.domains.map((d) => option(d, d)));
      if (lockedDomain) {
        domain.replaceChildren(option(lockedDomain, lockedDomain));
        domain.value = lockedDomain;
        domain.disabled = true;
      }
      const gran = h('select', null, [['MONTH', 'Mensual'], ['QUARTER', 'Trimestral'], ['SEMESTER', 'Semestral'], ['YEAR', 'Anual']].map(([v, label]) => option(v, label)));
      const today = new Date(), first = new Date(today); first.setDate(first.getDate() - 364);
      const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      start.value = iso(first); end.value = iso(today);
      const filters = () => ({ start_date: start.value, end_date: end.value, unit_id: unit.value, auditor_id: auditor.value, audit_domain: lockedDomain || domain.value, granularity: gran.value });
      const output = h('div', { class: 'ctl-dashboard-output' });
      const filterBar = h('div', { class: 'panel ctl-filters' },
        h('div', { class: 'toolbar' },
          h('label', null, 'Desde', start), h('label', null, 'Hasta', end),
          h('label', null, 'Unidad / sucursal', unit), h('label', null, 'Auditor asignado', auditor),
          h('label', null, isDomainHead ? 'Dominio supervisado' : 'Dominio', domain), h('label', null, 'Histórico', gran),
          h('button', { onclick: () => load() }, 'Aplicar filtros'),
          isContralor && can('kpi:manage') ? h('button', { class: 'secondary', onclick: () => saveSnapshot() }, 'Guardar corte histórico') : null,
          isContralor ? h('button', { class: 'secondary', onclick: () => openPrintReport() }, 'Vista imprimible') : null,
          isContralor && can('kpi:export') ? h('button', { class: 'secondary', onclick: () => downloadPdf() }, 'Exportar PDF') : null,
          isContralor && can('kpi:export') ? h('button', { class: 'secondary', onclick: () => downloadExport() }, 'Exportar Excel') : null));
      el.append(filterBar, output);

      async function downloadExport() {
        const r = await S.call('/analytics/contralor/export.xlsx?' + queryString(filters()));
        if (!r.ok || !r.blob) { S.say(S.err(r)); return; }
        S.download(r.blob, `SICAS_dashboard_contralor_${start.value}_${end.value}.xlsx`);
      }

      async function downloadPdf() {
        const r = await S.call('/analytics/contralor/export.pdf?' + queryString(filters()));
        if (!r.ok || !r.blob) { S.say(S.err(r)); return; }
        S.download(r.blob, `SICAS_dashboard_contralor_${start.value}_${end.value}.pdf`);
      }

      async function saveSnapshot() {
        const r = await S.send('/analytics/contralor/snapshots?' + queryString(filters()), 'POST', {});
        if (r) { S.say('Corte histórico guardado.', true); await load(); }
      }

      function openPrintReport() {
        (async () => {
          const reportWindow = window.open('about:blank', '_blank');
          if (!reportWindow) {
            S.say('Permita las ventanas emergentes para abrir el informe.');
            return;
          }
          reportWindow.opener = null;
          const session = await S.get('/analytics/contralor/options');
          if (!session) {
            reportWindow.close();
            return;
          }
          reportWindow.location.replace(
            '/api/v1/analytics/contralor/report?' + queryString(filters())
          );
        })();
      }

      async function loadSnapshots(target) {
        const data = await S.get('/analytics/contralor/snapshots?limit=12');
        if (!data) return;
        target.replaceChildren(
          emptyText('Los cortes almacenan métricas agregadas y resultados KPI del momento. No modifican auditorías, observaciones ni cédulas.'),
          data.snapshots.length ? tbl(['Fecha del corte', 'Captura UTC', 'Origen', 'Auditorías', 'Cerradas', 'Brechas', 'Altas/críticas', 'Incidencias calidad', 'KPI guardados'],
            data.snapshots.map((v) => [v.snapshot_date, v.created_at, v.source, v.summary?.audits_total ?? '—',
              v.summary?.audits_closed ?? '—', v.summary?.observations_total ?? '—',
              v.summary?.high_risk_observations ?? '—', v.data_quality?.issues_total ?? '—', v.kpi_count]))
            : emptyText('Aún no hay cortes guardados. Guarda el primer corte con el botón superior.')
        );
      }

      function kpiForm(existing = null, headMode = false) {
        const headOnlyMetrics = new Set(['INGESTION_AVG_SECONDS', 'INGESTION_REJECTION_PCT']);
        const metricOptions = METRIC_ORDER
          .filter((code) => options.metrics[code] && (!headMode || !headOnlyMetrics.has(code)))
          .map((code) => [code, `${options.metrics[code].label} (${options.metrics[code].unit})`]);
        const scopeOptions = headMode
          ? [['AUDITOR', 'Un auditor']]
          : [['GENERAL', 'Institucional'], ['UNIDAD', 'Una unidad / sucursal'], ['AUDITOR', 'Un auditor']];
        const unitOptions = options.units.map((u) => [String(u.id), `${u.code} — ${u.name}`]);
        const auditorOptions = options.auditors.map((u) => [u.id, u.name]);
        const fields = [
          { name: 'name', label: 'Nombre del KPI', value: existing?.name || '', required: true },
          { name: 'description', label: 'Descripción', type: 'textarea', value: existing?.description || '' },
          { name: 'metric_code', label: 'Métrica / fórmula autorizada', type: 'select', options: metricOptions, value: existing?.metric_code || 'AUDITS_TOTAL', required: true },
          { name: 'periodicity', label: 'Periodicidad', type: 'select', options: PERIODS, value: existing?.periodicity || 'MENSUAL', required: true },
          { name: 'scope_type', label: 'Alcance', type: 'select', options: scopeOptions, value: existing?.scope_type || (headMode ? 'AUDITOR' : 'GENERAL'), required: true },
        ];
        if (!headMode) {
          fields.push({ name: 'unit_id', label: 'ID de unidad (solo alcance Unidad)', type: 'select', options: [['', 'No aplica'], ...unitOptions], value: existing?.unit_id == null ? '' : String(existing.unit_id) });
        }
        fields.push(
          { name: 'auditor_id', label: 'Auditor (solo alcance Auditor)', type: 'select', options: [['', 'Seleccione un auditor'], ...auditorOptions], value: existing?.auditor_id || '', required: headMode || existing?.scope_type === 'AUDITOR' },
          { name: 'direction', label: 'Objetivo de la meta', type: 'select', options: [['AT_LEAST', 'Cumplir o superar la meta'], ['AT_MOST', 'No superar la meta']], value: existing?.direction || 'AT_LEAST', required: true },
          { name: 'target_value', label: 'Meta numérica', type: 'number', value: existing ? String(existing.target_value) : '', required: true },
          { name: 'warning_value', label: 'Umbral de advertencia (opcional)', type: 'number', value: existing?.warning_value == null ? '' : String(existing.warning_value) },
        );
        return S.ask(existing ? 'Editar KPI' : 'Crear KPI', fields,
          existing ? 'Guardar cambios' : 'Crear KPI',
          headMode
            ? 'Este KPI medirá a un auditor del dominio que usted supervisa. El alcance y las métricas disponibles están restringidos.'
            : 'La fórmula procede del catálogo autorizado; no se permite introducir SQL ni expresiones de código.');
      }

      function normalizeKpiPayload(v, headMode = false) {
        if (headMode) {
          v.scope_type = 'AUDITOR';
          v.unit_id = null;
        } else if (v.scope_type === 'GENERAL') {
          v.unit_id = null;
          v.auditor_id = null;
        } else if (v.scope_type === 'UNIDAD') {
          v.auditor_id = null;
        } else {
          v.unit_id = null;
        }
        v.target_value = Number(v.target_value);
        v.warning_value = v.warning_value === '' ? null : Number(v.warning_value);
        return v;
      }

      async function loadKpis(target, headMode = false) {
        const base = headMode ? '/analytics/contralor/kpis/mine' : '/analytics/contralor/kpis';
        const canManageKpis = headMode || can('kpi:manage');
        const data = await S.get(`${base}?all=1`);
        if (!data) return;
        const historyBox = h('div', { class: 'ctl-kpi-history' });
        target.replaceChildren(h('div', { class: 'row between' }, h('p', { class: 'muted' },
          headMode
            ? 'Solo aparecen KPI creados por usted para auditores asignados a su dominio. La medición respeta el dominio incluso en el cálculo.'
            : 'Las metas se evalúan en el período de cada KPI. Las definiciones inactivas se conservan para trazabilidad.'),
          canManageKpis ? h('button', { onclick: async () => {
            const v = await kpiForm(null, headMode); if (!v) return;
            normalizeKpiPayload(v, headMode);
            const r = await S.send(base, 'POST', v);
            if (r) { S.say('KPI creado.', true); await load(); }
          } }, 'Crear KPI') : null),
          data.kpis.length ? tbl(['Estado', 'KPI', 'Métrica', 'Período evaluado', 'Alcance', 'Real', 'Meta', 'Advertencia', 'Resultado', ''], data.kpis.map((k) => [
            k.active ? S.badge(k.status_result) : S.badge('INACTIVE'), k.name, k.metric.label,
            `${k.period_start} a ${k.period_end}`, k.scope_type === 'UNIDAD' ? k.unit_name : k.scope_type === 'AUDITOR' ? k.auditor_name : 'Institucional',
            fmt(k.actual_value, k.metric.unit === '%' ? '%' : ''), fmt(k.target_value, k.metric.unit === '%' ? '%' : ''), fmt(k.warning_value, k.metric.unit === '%' ? '%' : ''),
            S.badge(k.status_result), canManageKpis && k.active ? h('div', { class: 'actions' },
              h('button', { class: 'sm secondary', onclick: async () => {
                const history = await S.get(`${base}/${k.id}/history?limit=24`);
                if (!history) return;
                historyBox.replaceChildren(h('h4', null, `Historial: ${k.name}`),
                  history.measurements.length ? tbl(['Corte', 'Período evaluado', 'Real', 'Meta', 'Advertencia', 'Estado'], history.measurements.map((m) => [
                    m.snapshot_date, `${m.period_start} a ${m.period_end}`, fmt(m.actual_value, k.metric.unit === '%' ? '%' : ''),
                    fmt(m.target_value, k.metric.unit === '%' ? '%' : ''), fmt(m.warning_value, k.metric.unit === '%' ? '%' : ''), S.badge(m.status_result)]))
                    : emptyText('Este KPI aún no tiene mediciones guardadas en cortes históricos.'));
              } }, 'Historial'),
              h('button', { class: 'sm secondary', onclick: async () => {
                const v = await kpiForm(k, headMode); if (!v) return;
                normalizeKpiPayload(v, headMode);
                const r = await S.send(`${base}/${k.id}`, 'PATCH', v);
                if (r) { S.say('KPI actualizado.', true); await load(); }
              } }, 'Editar'),
              h('button', { class: 'sm secondary', onclick: async () => {
                if (!confirm(`¿Desactivar el KPI «${k.name}»? La definición se conservará.`)) return;
                if (await S.send(`${base}/${k.id}`, 'PATCH', { active: false })) { S.say('KPI desactivado.', true); await load(); }
              } }, 'Desactivar')) : ''])) : emptyText('Todavía no hay KPI configurados.'), historyBox);
      }

      async function load() {
        if (start.value && end.value && start.value > end.value) { S.say('La fecha inicial no puede ser posterior a la fecha final.'); return; }
        output.replaceChildren(h('p', { class: 'muted' }, 'Cargando indicadores…'));
        const data = await S.get('/analytics/contralor/overview?' + queryString(filters()));
        if (!data) { output.replaceChildren(); return; }
        const s = data.summary, risks = data.observations_by_risk;
        const cards = isGerencia ? null : h('div', { class: 'cards ctl-cards' },
          S.stat(fmt(s.audits_total), 'Auditorías del período'), S.stat(fmt(s.audits_in_progress), 'Auditorías en curso'),
          S.stat(fmt(s.audits_closed), 'Cerradas dentro de la cohorte'), S.stat(fmt(s.pending_approval), 'Informes pendientes de aprobación'),
          S.stat(fmt(s.observations_total), 'Brechas / observaciones'), S.stat(fmt(s.high_risk_observations), 'Brechas altas o críticas'),
          S.stat(fmt(s.avg_closed_audit_days, ' días'), 'Duración media de auditorías cerradas'), S.stat(fmt(s.avg_open_days, ' días'), 'Edad media de auditorías no cerradas'));
        const domainPanel = panel(
          isDomainHead ? `Resumen del dominio ${lockedDomain}` : 'Comparativo FINANCIERA vs SISTEMAS', h('div', null,
          emptyText(isDomainHead
            ? 'Los datos de esta vista están restringidos en el servidor al dominio asignado a este Jefe de Auditoría.'
            : 'Las auditorías se cuentan por fecha de creación y las observaciones por su propia fecha. Esta comparación mantiene ambos dominios visibles aunque el filtro Dominio seleccione uno; respeta las fechas, la unidad y el auditor.'),
          tbl(['Dominio', 'Auditorías', 'En curso', 'Cerradas', 'Brechas', 'Abiertas', 'Críticas', 'Altas', 'Medias', 'Bajas', 'Sin ítem', 'Criterios vinculados', 'Ítems calificados / total', '% alto/crítico'],
            data.by_domain.map((r) => [r.audit_domain, r.audits_total, r.audits_in_progress, r.audits_closed,
              r.observations_total, r.observations_open, r.critical_observations, r.high_risk_observations,
              r.medium_observations, r.low_observations, r.observations_without_item, r.criteria_with_formal_observation,
              `${fmt(r.items_scored)} / ${fmt(r.items_total)} (${fmt(r.items_scored_pct, '%')})`, fmt(r.high_risk_pct, '%')]))));
        const riskRows = Object.entries(risks).map(([level, value]) => ({ level, ...value })).filter((r) => r.total || r.open);
        const riskPanel = panel('Brechas por nivel de riesgo', h('div', null,
          barList(riskRows, (r) => prettyRisk(r.level), (r) => r.total, (r) => `${prettyRisk(r.level)}: ${r.total} total; ${r.open} abiertas`),
          tbl(['Riesgo', 'Total', 'Abiertas'], riskRows.map((r) => [prettyRisk(r.level), r.total, r.open]))));
        const trendPanel = panel('Histórico de auditorías y observaciones', h('div', null, chartLegend(), trendChart(data.trend),
          emptyText('Auditorías agrupadas por fecha de apertura; brechas agrupadas por su propia fecha de creación. Las cerradas son el estado actual de las auditorías abiertas en cada cohorte, no un conteo de cierres efectuados dentro del período.')));
        const heat = (value, band) => h('span', { class: `ctl-heat-cell ${Number(value) === 0 ? 'ctl-heat-zero' : `ctl-heat-${band}`}` }, fmt(value));
        const unitRiskPanel = panel('Mapa de calor: brechas por riesgo y unidad', tbl(
          ['Unidad', 'Crítico', 'Alto', 'Medio', 'Bajo', 'Sin clasificar', 'Otros', 'Total'],
          data.by_unit.map((r) => [r.unit_name, heat(r.risk_breakdown.CRITICAL || 0, 'high'), heat(r.risk_breakdown.HIGH || 0, 'high'),
            heat(r.risk_breakdown.MEDIUM || 0, 'mid'), heat(r.risk_breakdown.LOW || 0, 'low'), heat(r.risk_breakdown.UNSPECIFIED || 0, 'low'), heat(r.risk_breakdown.OTHER || 0, 'mid'), fmt(r.observations_total)])));
        const byUnitPanel = panel('Comparativo por unidad / sucursal', tbl(
          ['Unidad', 'Auditorías creadas', 'En curso', 'Cerradas de la cohorte', 'Brechas creadas', 'Alto/crítico', 'Brechas abiertas', 'Días promedio al cierre'],
          data.by_unit.map((r) => [r.unit_name, r.audits_total, r.audits_in_progress, r.audits_closed, r.observations_total, r.high_risk_observations, r.observations_open, fmt(r.avg_closed_audit_days)])));
        const phasePanel = panel('Tiempo transcurrido por fase', h('div', null,
          tbl(['Fase', 'Transiciones', 'Promedio horas'], data.phase_times.map((r) => [S.label2(r.phase), r.transitions, fmt(r.average_hours)])),
          emptyText('Duración de calendario entre transiciones registradas; no representa tiempo de trabajo activo. Si no existe historial de fase, no se inventa una duración de cierre.')));
        const auditorPanel = panel('Comparativo por auditor asignado', tbl(
          ['Auditor', 'Auditorías de cohorte asignadas', 'Cerradas de la cohorte', 'Días promedio al cierre'],
          data.by_auditor.map((r) => [r.auditor_name, r.audits_total, r.audits_closed, fmt(r.avg_closed_audit_days)])));
        const ing = data.ingestion;
        const ingestionPanel = isDomainHead ? null : panel('Cargas de datos — alcance global', h('div', null,
          h('div', { class: 'cards ctl-ingestion-cards' },
            S.stat(fmt(ing.jobs_total), 'Cargas iniciadas'), S.stat(fmt(ing.jobs_failed), 'Cargas fallidas'),
            S.stat(fmt(ing.rows_processed), 'Filas procesadas'), S.stat(fmt(ing.rows_rejected), 'Filas rechazadas'),
            S.stat(fmt(ing.average_seconds, ' s'), 'Duración media de carga'), S.stat(fmt(ing.rejection_pct, '%'), 'Porcentaje de rechazo')),
          emptyText('El esquema actual no relaciona cada carga con una unidad; estos indicadores se muestran globalmente. Si filtra por auditor, se filtran las cargas realizadas por ese usuario.')));
        const alerts = data.alerts || [];
        const alertPanel = panel(`Centro de alertas y vencimientos (${fmt(data.alert_summary?.total || 0)})`, h('div', null,
          h('div', { class: 'cards ctl-cards' }, S.stat(fmt(data.alert_summary?.critical || 0), 'Críticas'), S.stat(fmt(data.alert_summary?.high || 0), 'Altas'),
            S.stat(fmt(data.alert_summary?.medium || 0), 'Medias'), S.stat(fmt(data.alert_summary?.overdue || 0), 'Vencidas')),
          emptyText('Se muestran hasta 250 alertas prioritarias. Los contadores resumen las filas mostradas; pueden existir más. Son del estado actual, respetan unidad, auditor y dominio, y no se recortan por la fecha histórica seleccionada.'),
          h('details', { class: 'ctl-alert-details' },
            h('summary', null, `Detalle de alertas (${fmt(alerts.length)})`),
            alerts.length ? tbl(['Nivel', 'Tipo', 'Auditoría', 'Dominio', 'Unidad', 'Detalle', 'Vencimiento', 'Antigüedad (días)', 'Fase'], alerts.map((a) => [
              S.badge(a.severity), a.alert_type, a.audit_code, a.domain, a.unit_name, a.detail, a.due_date || '—', fmt(a.days_overdue), S.label2(a.phase)]))
              : emptyText('No hay alertas para los filtros actuales.'))));
        const quality = data.data_quality || { checks: [], issues_total: 0 };
        const qualityPanel = panel(`Calidad e integridad de datos (${fmt(quality.issues_total)} alertas)`, h('div', null,
          emptyText('Las observaciones generales sin criterio son válidas. Los ítems sin calificación indican cobertura pendiente, no necesariamente un error.'),
          tbl(['Nivel', 'Control', 'Cantidad', 'Interpretación'], (quality.checks || []).map((c) => [S.badge(c.level), c.label, c.count, c.description]))));
        const pipe = data.phase_pipeline || { phases: [], pending_reports: [] };
        const pipelinePanel = panel('Flujo de auditoría y cuellos de botella', h('div', null,
          tbl(['Fase actual', 'Auditorías activas', 'Vencidas', 'Horas transcurridas promedio'], pipe.phases.map((r) => [S.label2(r.phase), r.audits, r.overdue, fmt(r.average_phase_hours)])),
          tbl(['Estado del informe pendiente', 'Informes'], pipe.pending_reports.map((r) => [r.status, r.reports]))));
        const workloadPanel = panel('Carga y tiempo activo registrado por auditor', h('div', null,
          tbl(['Auditor', 'Auditorías activas', 'Vencidas', 'Brechas altas abiertas', 'Edad promedio (días)', 'Horas activas registradas', 'Sesiones'], (data.workload || []).map((r) => [
            r.auditor_name, r.active_audits, r.overdue_audits, r.open_high_risk, fmt(r.average_open_age_days), fmt(r.tracked_active_hours), r.tracked_sessions || 0])),
          emptyText('Las horas provienen del cronómetro de inicio/pausa/reanudación/finalización del auditor; son tiempo activo declarado, no una medición de teclado.')));
        const snapshotPanel = panel('Histórico verificable de cortes y KPI', h('div', { class: 'ctl-snapshots-host' }));
        const kpiPanel = panel(isDomainHead ? 'KPI de mis auditores' : 'KPI configurables y su historial', h('div', { class: 'ctl-kpi-host' }));
        // Navegación por secciones: conserva todos los paneles y datos, pero evita
        // presentar una página interminable. Los paneles ocultos siguen en el DOM.
        const dashboardSections = [
          { id: 'resumen', label: 'Resumen', content: [cards, domainPanel, alertPanel] },
          { id: 'brechas', label: 'Brechas y riesgos', content: [
            h('div', { class: 'ctl-chart-grid' }, riskPanel, trendPanel),
            h('div', { class: 'ctl-chart-grid' }, unitRiskPanel, byUnitPanel)
          ] },
          { id: 'seguimiento', label: 'Seguimiento', content: [
            h('div', { class: 'ctl-chart-grid' }, phasePanel, pipelinePanel),
            h('div', { class: 'ctl-chart-grid' }, auditorPanel, workloadPanel)
          ] },
          { id: 'calidad', label: isDomainHead ? 'Calidad de datos' : 'Calidad y cargas', content: [
            h('div', { class: 'ctl-chart-grid' }, qualityPanel, isDomainHead ? null : ingestionPanel)
          ] },
          ...(isContralor ? [
            { id: 'historico', label: 'Histórico y KPI', content: [snapshotPanel, kpiPanel] }
          ] : []),
          ...(isDomainHead ? [
            { id: 'mis-kpi', label: 'KPI de mis auditores', content: [kpiPanel] }
          ] : [])
        ];
        const tabButtons = dashboardSections.map((section, index) => {
          const button = h('button', { class: `ctl-tab-button${index === 0 ? ' is-active' : ''}`, type: 'button', role: 'tab' }, section.label);
          button.dataset.ctlTab = section.id;
          button.setAttribute('aria-controls', `ctl-tab-panel-${section.id}`);
          button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
          button.tabIndex = index === 0 ? 0 : -1;
          button.addEventListener('click', () => activateSection(section.id));
          button.addEventListener('keydown', (event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const currentIndex = dashboardSections.findIndex((item) => item.id === section.id);
            const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? dashboardSections.length - 1
              : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + dashboardSections.length) % dashboardSections.length;
            tabButtons[nextIndex].focus();
            activateSection(dashboardSections[nextIndex].id);
          });
          return button;
        });
        const tabPanels = dashboardSections.map((section, index) => {
          const panelNode = h('section', { class: `ctl-tab-panel${index === 0 ? ' is-active' : ''}`, id: `ctl-tab-panel-${section.id}`, role: 'tabpanel' }, ...section.content);
          panelNode.dataset.ctlPanel = section.id;
          panelNode.hidden = index !== 0;
          return panelNode;
        });
        function activateSection(id) {
          tabButtons.forEach((button) => {
            const active = button.dataset.ctlTab === id;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
            button.tabIndex = active ? 0 : -1;
          });
          tabPanels.forEach((panelNode) => {
            const active = panelNode.dataset.ctlPanel === id;
            panelNode.hidden = !active;
            panelNode.classList.toggle('is-active', active);
          });
        }
        const tabs = h('div', { class: 'ctl-tabs', role: 'tablist', 'aria-label': 'Secciones del Dashboard SICAS' }, ...tabButtons);
        const workspace = h('div', { class: 'ctl-workspace' }, tabs, ...tabPanels);
        output.replaceChildren(workspace);
        if (isContralor) {
          await loadSnapshots(snapshotPanel.querySelector('.ctl-snapshots-host'));
          await loadKpis(kpiPanel.querySelector('.ctl-kpi-host'));
        } else if (isDomainHead) {
          await loadKpis(kpiPanel.querySelector('.ctl-kpi-host'), true);
        }
      }
      load();
    }
  });
})();
