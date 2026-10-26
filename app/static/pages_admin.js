// SICAS — Inicio, usuarios, solicitudes de rol, auditoría del sistema y sistema.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, badge, fmt } = S;

  // SICAS-HOME-DASHBOARD-20261014-v1
  S.pages.push({
    id: 'home',
    title: 'Inicio',
    perms: [],
    render: async (el) => {
      el.classList.add('home-dashboard');

      const hasAnalytics = can('dashboard:operational', 'dashboard:executive');
      const hasAuditAccess = can('audit:read');
      const hasReportAccess = can(
        'audit:report_approve', 'audit:sign_gerente', 'audit:read_final'
      );

      // Reutilizar las consultas existentes; no se introducen endpoints nuevos.
      const overview = hasAnalytics
        ? await S.get('/analytics/overview')
        : null;

      const auditData = hasAuditAccess
        ? await S.get('/audits')
        : null;

      const reportData = hasReportAccess
        ? await S.get('/audits/final-reports')
        : null;

      const audits = Array.isArray(auditData?.audits)
        ? auditData.audits : [];

      const reports = Array.isArray(reportData?.reports)
        ? reportData.reports : [];

      const activeAudits = audits.filter(
        (a) => a.status === 'IN_PROGRESS'
      );

      const activeFileCodes = new Set(
        activeAudits.map((a) => a.file_code).filter(Boolean)
      );

      const pendingReports = reports.filter(
        (r) => r.status !== 'SIGNED'
      );

      const severity = overview?.open_findings_by_severity || {};
      const totalFindings = Object.values(severity).reduce(
        (sum, value) => sum + (Number(value) || 0), 0
      );

      const failedUploads = (overview?.ingestion || [])
        .filter((job) => job.status === 'FAILED')
        .reduce((sum, job) => sum + (Number(job.n) || 0), 0);

      const number = (value) => Number(value || 0).toLocaleString('es-ES');

      const statusName = (value) => ({
        IN_PROGRESS: 'En curso',
        CLOSED: 'Cerrada',
        SIGNED: 'Firmado',
        APPROVED: 'Aprobado',
        PENDING: 'Pendiente',
        DRAFT: 'Borrador',
        OPEN: 'Abierto',
        UNDER_REVIEW: 'En revisión',
        IN_REVIEW: 'En revisión',
        CANCELLED: 'Cancelada',
        REJECTED: 'Rechazado',
        RETURNED: 'Devuelto'
      })[value] || String(value || 'Sin estado')
        .replaceAll('_', ' ');

      const statusBadge = (value) => {
        const node = S.badge(value || '—');
        if (node && value) node.textContent = statusName(value);
        return node;
      };

      const header = h('div', { class: 'home-dashboard-header' });
      const intro = h('div', { class: 'home-dashboard-intro' });

      intro.append(
        h('p', { class: 'home-eyebrow' }, 'SICAS · CONTROL Y AUDITORÍA'),
        h('h2', null, 'Inicio'),
        h('p', { class: 'home-subtitle' },
          'Resumen operativo de auditorías, expedientes e informes.')
      );

      const live = h('span', { class: 'home-live-badge' });
      live.append(
        h('span', { class: 'home-live-dot' }),
        document.createTextNode(' Datos del sistema')
      );

      header.append(intro, live);
      el.append(header);

      // Indicadores: solo métricas respaldadas por los datos accesibles.
      const metrics = h('div', { class: 'cards home-metrics' });

      const addMetric = (value, label) => {
        metrics.append(S.stat(number(value), label));
      };

      if (hasAuditAccess) {
        addMetric(activeAudits.length, 'Auditorías en curso');
        addMetric(activeFileCodes.size, 'Expedientes con actividad');
      }

      if (hasReportAccess) {
        addMetric(pendingReports.length, 'Informes por atender');
      }

      if (overview) {
        addMetric(totalFindings, 'Hallazgos abiertos');
        addMetric(Number(severity.CRITICAL || 0), 'Hallazgos críticos');

        if (failedUploads > 0) {
          addMetric(failedUploads, 'Cargas fallidas');
        }
      }

      if (metrics.children.length) {
        el.append(metrics);
      } else {
        el.append(h('section', { class: 'home-panel home-empty-access' },
          h('h3', null, 'Resumen operativo'),
          h('p', null,
            'El resumen depende de los permisos asignados a su usuario.')));
      }

      // Construcción de gráficas con datos reales.
      const countBy = (items, getLabel) => {
        const counts = new Map();

        items.forEach((item) => {
          const label = String(getLabel(item) || 'Sin dato');
          counts.set(label, (counts.get(label) || 0) + 1);
        });

        return [...counts.entries()]
          .map(([label, value]) => ({ label, value }))
          .sort((a, b) => b.value - a.value);
      };

      const chartPanel = (title, subtitle, items) => {
        const panel = h('section', { class: 'home-panel home-chart-panel' });
        const heading = h('div', { class: 'home-panel-head' });
        const copy = h('div', { class: 'home-panel-title' });

        copy.append(
          h('h3', null, title),
          h('p', { class: 'home-panel-note' }, subtitle)
        );

        heading.append(copy);
        panel.append(heading);

        if (!items.length) {
          panel.append(h('p', { class: 'home-empty' },
            'No hay datos disponibles para esta visualización.'));
          return panel;
        }

        const maxValue = Math.max(
          1, ...items.map((item) => Number(item.value) || 0)
        );

        const bars = h('div', { class: 'home-bars' });

        items.forEach((item, index) => {
          const value = Number(item.value) || 0;
          const percentage = Math.round(value / maxValue * 100);
          const row = h('div', { class: 'home-bar-row' });
          const meta = h('div', { class: 'home-bar-meta' });

          meta.append(
            h('span', { class: 'home-bar-label' }, item.label),
            h('strong', { class: 'home-bar-value' }, number(value))
          );

          const track = h('div', { class: 'home-bar-track' });
          const fill = h('span', {
            class: 'home-bar-fill tone-' + (index % 5)
          });

          fill.style.width = percentage + '%';
          track.append(fill);
          row.append(meta, track);
          bars.append(row);
        });

        panel.append(bars);
        return panel;
      };

      // Gráfico de líneas SVG sin bibliotecas externas.
      const lineChartPanel = (title, subtitle, labels, series) => {
        const panel = h('section', {
          class: 'home-panel home-chart-panel home-line-panel'
        });
        const heading = h('div', { class: 'home-panel-head' });
        const copy = h('div', { class: 'home-panel-title' });

        copy.append(
          h('h3', null, title),
          h('p', { class: 'home-panel-note' }, subtitle)
        );
        heading.append(copy);
        panel.append(heading);

        if (labels.length < 2 || !series.length) {
          panel.append(h('p', { class: 'home-empty' },
            'No hay suficientes fechas válidas para calcular una tendencia.'));
          return panel;
        }

        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        const width = 720;
        const height = 300;
        const pad = { left: 48, right: 20, top: 22, bottom: 48 };
        const plotWidth = width - pad.left - pad.right;
        const plotHeight = height - pad.top - pad.bottom;
        const maxValue = Math.max(
          1,
          ...series.flatMap((item) => item.values)
        );
        const scaleMax = Math.max(4, Math.ceil(maxValue / 4) * 4);
        const palette = ['#3479b8', '#319c91', '#8065c8', '#dc9b31', '#d35e69'];

        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.setAttribute('role', 'img');
        svg.setAttribute(
          'aria-label',
          title + ': evolución mensual de auditorías por unidad'
        );
        svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        svg.classList.add('home-line-chart');

        const makeSvg = (tag, attrs, text) => {
          const node = document.createElementNS(ns, tag);
          Object.entries(attrs || {}).forEach(([key, value]) =>
            node.setAttribute(key, String(value))
          );
          if (text != null) node.textContent = String(text);
          return node;
        };

        // Ejes y cuadrícula.
        for (let tick = 0; tick <= 4; tick++) {
          const value = scaleMax * tick / 4;
          const y = pad.top + plotHeight - (value / scaleMax) * plotHeight;

          svg.append(
            makeSvg('line', {
              x1: pad.left,
              y1: y,
              x2: width - pad.right,
              y2: y,
              stroke: '#e5edf5',
              'stroke-width': 1
            }),
            makeSvg('text', {
              x: pad.left - 10,
              y: y + 4,
              fill: '#74869a',
              'font-size': 11,
              'text-anchor': 'end'
            }, Math.round(value))
          );
        }

        labels.forEach((label, index) => {
          const x = pad.left + (
            labels.length === 1
              ? plotWidth / 2
              : index * plotWidth / (labels.length - 1)
          );

          svg.append(makeSvg('text', {
            x,
            y: height - 18,
            fill: '#647890',
            'font-size': 11,
            'text-anchor': 'middle'
          }, label));
        });

        const legend = h('div', { class: 'home-line-legend' });

        series.forEach((item, seriesIndex) => {
          const color = palette[seriesIndex % palette.length];
          const points = item.values.map((value, index) => ({
            x: pad.left + index * plotWidth / (labels.length - 1),
            y: pad.top + plotHeight -
              (Number(value || 0) / scaleMax) * plotHeight,
            value: Number(value || 0)
          }));

          const pointText = points.map((point) =>
            `${point.x},${point.y}`
          ).join(' ');

          svg.append(makeSvg('polyline', {
            points: pointText,
            fill: 'none',
            stroke: color,
            'stroke-width': 2.5,
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round'
          }));

          points.forEach((point, index) => {
            const circle = makeSvg('circle', {
              cx: point.x,
              cy: point.y,
              r: 4,
              fill: color,
              stroke: '#fff',
              'stroke-width': 1.5
            });

            circle.append(makeSvg(
              'title',
              {},
              `${item.label}, ${labels[index]}: ${point.value} auditorías`
            ));
            svg.append(circle);
          });

          const legendItem = h('span', { class: 'home-line-legend-item' });
          const swatch = h('span', { class: 'home-line-swatch' });
          swatch.style.backgroundColor = color;
          legendItem.append(swatch, document.createTextNode(item.label));
          legend.append(legendItem);
        });

        panel.append(svg, legend);
        return panel;
      };

      // Dona de severidad; conserva los conteos y porcentajes reales.
      const severityDonutPanel = (values) => {
        const panel = h('section', {
          class: 'home-panel home-chart-panel home-severity-panel'
        });
        const heading = h('div', { class: 'home-panel-head' });
        const copy = h('div', { class: 'home-panel-title' });

        copy.append(
          h('h3', null, 'Hallazgos abiertos por severidad'),
          h('p', { class: 'home-panel-note' },
            'Distribución de los hallazgos informados por el sistema')
        );
        heading.append(copy);
        panel.append(heading);

        const rows = [
          { key: 'CRITICAL', label: 'Críticos', color: '#d9485f' },
          { key: 'HIGH', label: 'Altos', color: '#ed8b32' },
          { key: 'MEDIUM', label: 'Medios', color: '#e0b13e' },
          { key: 'LOW', label: 'Bajos', color: '#3479b8' }
        ].map((row) => ({
          ...row,
          value: Math.max(0, Number(values[row.key] || 0))
        }));

        const total = rows.reduce((sum, row) => sum + row.value, 0);
        const layout = h('div', { class: 'home-donut-layout' });
        const ring = h('div', {
          class: 'home-donut-ring',
          role: 'img',
          'aria-label': `Total de hallazgos abiertos: ${number(total)}`
        });

        if (total > 0) {
          let offset = 0;
          const stops = [];

          rows.filter((row) => row.value > 0).forEach((row) => {
            const end = offset + row.value / total * 100;
            stops.push(
              `${row.color} ${offset.toFixed(2)}% ${end.toFixed(2)}%`
            );
            offset = end;
          });

          ring.style.background = `conic-gradient(${stops.join(', ')})`;
        } else {
          ring.style.background = '#e7edf4';
        }

        const hole = h('div', { class: 'home-donut-center' });
        hole.append(
          h('strong', null, number(total)),
          h('span', null, 'abiertos')
        );
        ring.append(hole);
        layout.append(ring);

        const legend = h('div', { class: 'home-donut-legend' });

        rows.forEach((row) => {
          const legendRow = h('div', { class: 'home-donut-row' });
          const name = h('span', { class: 'home-donut-name' });
          const swatch = h('span', { class: 'home-donut-swatch' });
          swatch.style.backgroundColor = row.color;
          name.append(swatch, document.createTextNode(row.label));

          const count = h('strong', { class: 'home-donut-count' },
            number(row.value));
          const percentage = total
            ? Math.round(row.value / total * 100)
            : 0;

          legendRow.append(
            name,
            count,
            h('span', { class: 'home-donut-percent' }, percentage + '%')
          );
          legend.append(legendRow);
        });

        layout.append(legend);
        panel.append(layout);
        return panel;
      };

      const charts = h('div', { class: 'home-chart-grid' });

      // Evolución mensual solo si la API ya proporciona fechas válidas.
      const auditDate = (audit) => {
        for (const key of [
          'created_at', 'created_on', 'createdAt', 'created', 'started_at'
        ]) {
          if (!audit?.[key]) continue;

          const date = new Date(audit[key]);
          if (Number.isFinite(date.getTime())) return date;
        }
        return null;
      };

      // SICAS-HOME-UNIT-PERIOD-CHARTS-20261014-v2
      const datedAudits = audits
        .map((audit) => ({ audit, date: auditDate(audit) }))
        .filter((item) => item.date);

      if (hasAuditAccess) {
        const statuses = countBy(audits, (a) => statusName(a.status));
        const phases = countBy(audits, (a) =>
          a.phase && typeof S.label2 === 'function'
            ? S.label2(a.phase) : a.phase
        );

        // countBy ya ordena de mayor a menor por cantidad.
        const units = countBy(
          audits,
          (a) => a.unit_name || 'Sin unidad'
        ).slice(0, 5);

        charts.append(
          chartPanel(
            'Estado de auditorías',
            `${number(audits.length)} auditorías en la lista disponible`,
            statuses
          ),
          chartPanel(
            'Auditorías por fase',
            'Distribución según la fase actual',
            phases
          )
        );

        // 1. Ranking estático de unidades, siempre en barras.
        const ranking = chartPanel(
          'Unidades con más auditorías',
          'Total de auditorías por unidad, de mayor a menor',
          units
        );
        ranking.classList.add('home-units-ranking');
        charts.append(ranking);

        // 2. Tendencia de las mismas unidades a lo largo del tiempo.
        if (datedAudits.length && units.length) {
          const periodSelect = document.createElement('select');
          periodSelect.className = 'home-period-select';
          periodSelect.setAttribute('aria-label', 'Período de evolución');
          periodSelect.title = 'Cambiar período del gráfico';

          [
            { value: 'month', label: 'Mensual' },
            { value: 'quarter', label: 'Trimestral' }
          ].forEach(({ value, label }) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            periodSelect.appendChild(option);
          });

          const trendHost = h('div', { class: 'home-trend-host' });

          const renderUnitTrend = () => {
            const period = periodSelect.value;
            const bucketCount = period === 'quarter' ? 4 : 6;
            const now = new Date();

            const buckets = Array.from(
              { length: bucketCount },
              (_, index) => {
                const offset = index - (bucketCount - 1);
                const date = period === 'quarter'
                  ? new Date(
                      now.getFullYear(),
                      Math.floor(now.getMonth() / 3) * 3 + offset * 3,
                      1
                    )
                  : new Date(
                      now.getFullYear(),
                      now.getMonth() + offset,
                      1
                    );

                const label = period === 'quarter'
                  ? `T${Math.floor(date.getMonth() / 3) + 1} ${date.getFullYear()}`
                  : date.toLocaleDateString('es-ES', {
                      month: 'short',
                      year: '2-digit'
                    }).replace(/\.$/, '');

                return {
                  year: date.getFullYear(),
                  monthIndex: date.getMonth(),
                  quarter: Math.floor(date.getMonth() / 3),
                  label
                };
              }
            );

            const series = units.map((unit) => ({
              label: unit.label,
              values: buckets.map((bucket) =>
                datedAudits.filter(({ audit, date }) => {
                  if ((audit.unit_name || 'Sin unidad') !== unit.label) {
                    return false;
                  }

                  if (date.getFullYear() !== bucket.year) {
                    return false;
                  }

                  return period === 'quarter'
                    ? Math.floor(date.getMonth() / 3) === bucket.quarter
                    : date.getMonth() === bucket.monthIndex;
                }).length
              )
            }));

            const panel = lineChartPanel(
              period === 'quarter'
                ? 'Evolución trimestral por unidad'
                : 'Evolución mensual por unidad',
              period === 'quarter'
                ? 'Últimos cuatro trimestres con fechas disponibles'
                : 'Últimos seis meses con fechas disponibles',
              buckets.map((bucket) => bucket.label),
              series
            );

            panel.classList.add('home-unit-trend-panel');

            const heading = panel.querySelector('.home-panel-head');
            if (heading) heading.appendChild(periodSelect);

            trendHost.replaceChildren(panel);
          };

          periodSelect.addEventListener('change', renderUnitTrend);
          charts.append(trendHost);
          renderUnitTrend();
        } else {
          charts.append(chartPanel(
            'Evolución por unidad',
            'No hay fechas válidas suficientes para calcular una tendencia temporal.',
            []
          ));
        }
      }
      if (overview) {
        charts.append(severityDonutPanel(severity));
      }

      if (charts.children.length) {
        const sectionTitle = h('div', {
          class: 'home-section-heading'
        });

        sectionTitle.append(
          h('h3', null, 'Panorama operativo'),
          h('p', { class: 'home-panel-note' },
            'Las visualizaciones resumen los registros disponibles para su usuario.')
        );

        el.append(sectionTitle, charts);
      }

      // Tabla de auditorías: mantiene el detalle y la navegación existentes.
      const tablePanel = (
        title, subtitle, records, headers, rowMapper,
        emptyMessage, onRow
      ) => {
        const panel = h('section', { class: 'home-panel home-table-panel' });
        const head = h('div', { class: 'home-panel-head' });
        const text = h('div', { class: 'home-panel-title' });

        text.append(
          h('h3', null, title),
          h('p', { class: 'home-panel-note' }, subtitle)
        );

        head.append(text);

        const more = h('button', {
          type: 'button',
          class: 'home-link-button',
          onclick: () => { location.hash = '#/audits'; }
        }, 'Ver módulo →');

        head.append(more);
        panel.append(head);

        if (records.length) {
          const rows = records.map(rowMapper);
          panel.append(tbl(
            headers,
            rows,
            onRow ? (index) => onRow(records[index]) : undefined
          ));
        } else {
          panel.append(h('p', { class: 'home-empty' }, emptyMessage));
        }

        return panel;
      };

      const tables = h('div', { class: 'home-table-grid' });

      if (hasAuditAccess) {
        tables.append(tablePanel(
          'Auditorías recientes',
          'Acceso directo a los expedientes de auditoría',
          audits.slice(0, 6),
          ['Código', 'Expediente', 'Unidad', 'Fase', 'Estado'],
          (audit) => [
            audit.code || '—',
            audit.file_code || '—',
            audit.unit_name || '—',
            audit.phase && typeof S.label2 === 'function'
              ? S.label2(audit.phase) : (audit.phase || '—'),
            statusBadge(audit.status)
          ],
          auditData
            ? 'No hay auditorías registradas.'
            : 'No fue posible cargar las auditorías.',
          (audit) => {
            if (audit.id) location.hash = '#/audits/' + audit.id;
          }
        ));
      }

      if (hasReportAccess) {
        // Los pendientes aparecen primero, pero se conservan informes firmados.
        const prioritizedReports = [
          ...pendingReports,
          ...reports.filter((report) => report.status === 'SIGNED')
        ].slice(0, 6);

        tables.append(tablePanel(
          'Informes finales',
          'Estado de aprobación y número de firmas',
          prioritizedReports,
          ['Auditoría', 'Unidad', 'Estado', 'Firmas'],
          (report) => [
            report.audit_code || '—',
            report.unit_name || '—',
            statusBadge(report.status),
            String(report.signatures ?? 0) + ' / 2'
          ],
          reportData
            ? 'No hay informes finales disponibles.'
            : 'No fue posible cargar los informes.',
          (report) => {
            if (report.audit_id) {
              location.hash = '#/audits/' + report.audit_id + '/informes';
            }
          }
        ));
      }

      if (tables.children.length) {
        el.append(tables);
      }
    }
  });
  S.label2 = (p) => ({ PLANIFICACION: 'Planificación', TRABAJO_CAMPO: 'Trabajo de campo', INFORME: 'Informe', LEVANTAMIENTO: 'Levantamiento de información', DOCUMENTACION: 'Documentación', PRUEBAS_CAMPO: 'Pruebas de campo' })[p] || p;

  // ------------------------------------------------------------------ Usuarios
  S.pages.push({ id: 'users', title: 'Usuarios', perms: ['user:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Usuarios'));
      const d = await S.get('/admin/users');
      if (!d) return;
      const bar = h('div', { class: 'toolbar' });
      if (can('user:create')) bar.append(h('button', { onclick: newUser }, 'Nuevo usuario'));
      el.append(bar, tbl(['Usuario', 'Nombre', 'Correo', 'Roles', 'Estado', 'Último ingreso', 'Acciones'], d.users.map((u) => [
        u.username, u.full_name, u.email, (u.roles || []).map(S.roleLabel).join(', ') || h('span', { class: 'muted' }, 'sin roles'),
        [S.badge(u.is_active ? 'ACTIVE' : 'INACTIVE'), u.locked_until && new Date(u.locked_until) > new Date() ? h('span', { class: 'badge FAILED' }, 'Bloqueado') : null],
        fmt(u.last_login_at),
        h('div', { class: 'actions' },
          can('role:assign') ? h('button', { onclick: () => roleReq(u) }, 'Rol…') : null,
          can('user:unlock') ? h('button', { class: 'secondary', onclick: () => act(u, 'unlock', 'Desbloquear a ' + u.username) }, 'Desbloquear') : null,
          can('user:update') && u.is_active && S.requestAdminAction ? h('button', { class: 'secondary', onclick: async () => {
            const r = await S.requestAdminAction('RESET_PASSWORD', { user_id: u.id }, 'Restablecer la contraseña de ' + u.username,
              'Se genera una contraseña temporal nueva, se desbloquea la cuenta y se cierran sus sesiones; el usuario deberá cambiarla al ingresar.');
            if (r) S.say('Solicitud registrada. Cuando el Contralor la apruebe, vea la contraseña temporal aquí abajo, en «Solicitudes del Administrador».', true);
            draw();
          } }, 'Restablecer clave…') : null,
          can('user:reset_mfa') ? h('button', { class: 'secondary', onclick: () => act(u, 'reset-mfa', 'Restablecer el MFA de ' + u.username) }, 'Reset MFA') : null,
          can('user:deactivate') ? h('button', { class: u.is_active ? 'danger' : 'ok', onclick: () => act(u, u.is_active ? 'deactivate' : 'activate', (u.is_active ? 'Desactivar a ' : 'Activar a ') + u.username) }, u.is_active ? 'Desactivar' : 'Activar') : null,
          can('user:read') ? h('button', { class: 'secondary', title: 'Firmas escaneadas (Jefe que aprueba, Gerencia y Contralor)', onclick: () => signatures(u) }, 'Firmas…') : null,
          can('user:deactivate') ? h('button', { class: 'danger', title: 'Baja definitiva (requiere aprobación del Contralor)', onclick: () => removal(u) }, 'Baja…') : null)])));
    };
    const signatures = async (u) => {
      const d = await S.get(`/admin/users/${u.id}/signatures`);
      if (!d) return;
      const TYPES = { COMPLETA: 'Firma completa', MEDIA: 'Media firma' };
      const body = h('div', null,
        h('p', { class: 'muted' }, 'La firma escaneada aparece en el informe final de quien lo aprueba o firma: Jefe de Auditoría, Gerencia y Contralor. ' +
          'Los auditores del equipo solo estampan sus iniciales. Al reemplazar una firma, la anterior queda inactiva y se conserva.'),
        tbl(['Tipo', 'Firma', 'Archivo', 'Tamaño', 'Estado', 'Cargó', 'Fecha', ''], d.signatures.map((x) => [TYPES[x.signature_type] || x.signature_type,
          x.preview ? h('img', { src: x.preview, alt: 'Firma de ' + u.full_name, class: 'sig-preview' }) : '—',
          x.original_filename, `${x.width_px}×${x.height_px}`, S.badge(x.active ? 'ACTIVE' : 'INACTIVE'), x.created_by || '—', fmt(x.created_at),
          x.active && can('user:update') ? h('button', { class: 'sm danger', onclick: async () => {
            if (!confirm('¿Desactivar esta firma?')) return;
            if (await S.send(`/admin/users/${u.id}/signatures/${x.id}/deactivate`, 'POST')) { m.close(); signatures(u); }
          } }, 'Desactivar') : ''])));
      const m = S.modal('Firmas escaneadas: ' + u.full_name, body);
      if (can('user:update')) m.footer.append(h('button', { onclick: async () => {
        const v = await S.ask('Cargar firma escaneada', [
          { name: 'type', label: 'Tipo', type: 'select', options: [['COMPLETA', 'Firma completa'], ['MEDIA', 'Media firma']] },
          { name: 'file', label: 'Imagen PNG (fondo blanco o transparente, hasta 1 MB)', type: 'file', required: true }], 'Cargar');
        if (!v) return;
        const form = new FormData(); form.append('type', v.type); form.append('file', v.file);
        const r = await S.upload(`/admin/users/${u.id}/signatures`, form);
        if (!r.ok) return S.say(S.err(r));
        S.say('Firma registrada.', true); m.close(); signatures(u);
      } }, 'Cargar firma'));
      m.footer.append(h('button', { class: 'secondary', onclick: () => m.close() }, 'Cerrar'));
      // Solicitudes del Administrador (p. ej. ver la contraseña temporal de un restablecimiento aprobado).
      if (S.myAdminRequests && can('user:update')) { const panel = await S.myAdminRequests(draw); if (panel) el.append(panel); }
    };
    const removal = async (u) => {
      const v = await S.ask('Baja definitiva: ' + u.username, [
        { name: 'reason', label: 'Justificación (mínimo 15 caracteres)', type: 'textarea', required: true }], 'Solicitar baja',
        'La cuenta no se borra: se desactiva, pierde sus roles y sesiones y deja de mostrarse, porque la bitácora y las firmas la referencian. ' +
        'No podrá reactivarse. La baja se aplica cuando el Contralor la aprueba.');
      if (!v) return;
      const d = await S.send(`/admin/users/${u.id}/removal-request`, 'POST', v);
      if (d) S.say(d.note || 'Solicitud registrada.', true);
    };
    const act = async (u, what, title) => {
      if (!confirm(title + '?')) return;
      if (await S.send(`/admin/users/${u.id}/${what}`, 'POST')) { S.say('Hecho.', true); draw(); }
    };
    const newUser = async () => {
      const v = await S.ask('Nuevo usuario', [{ name: 'username', label: 'Usuario (minúsculas, sin espacios)', required: true }, { name: 'email', label: 'Correo', type: 'email', required: true },
        { name: 'full_name', label: 'Nombre completo', required: true }], 'Crear', 'Se crea sin roles; luego se solicita su rol y otra persona lo aprueba (doble control).');
      if (!v) return;
      const d = await S.send('/admin/users', 'POST', v);
      if (!d) return;
      const m = S.modal('Usuario creado', h('div', null, h('p', null, 'Entregue esta contraseña temporal al usuario por un canal seguro. Se muestra UNA sola vez.'), h('div', { class: 'temp' }, d.temporary_password)));
      m.footer.append(h('button', { onclick: () => { m.close(); draw(); } }, 'Entendido'));
    };
    const roleReq = async (u) => {
      const roles = await S.get('/admin/roles');
      if (!roles) return;
      const v = await S.ask('Solicitar cambio de rol: ' + u.username, [
        { name: 'action', label: 'Acción', type: 'select', options: [['GRANT', 'Otorgar rol'], ['REVOKE', 'Retirar rol']] },
        { name: 'role', label: 'Rol', type: 'select', options: roles.roles.map((r) => [r.code, r.code + ' — ' + r.description]) },
        { name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Solicitar', 'Queda pendiente hasta que otra persona autorizada lo apruebe.');
      if (!v) return;
      if (await S.send(`/admin/users/${u.id}/role-request`, 'POST', v)) S.say('Solicitud registrada: queda pendiente de aprobación.', true);
    };
    draw();
  } });

  // ------------------------------------------------------------------ Solicitudes de rol
  S.pages.push({ id: 'roles', title: 'Solicitudes', perms: ['role:approve', 'role:assign', 'role:read', 'admin:action_approve', 'audit:annul_approve', 'backup:restore_approve'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Solicitudes y aprobaciones'));
      if (S.adminApprovals) await S.adminApprovals(el, draw);
      if (!can('role:approve', 'role:assign', 'role:read')) return;
      el.append(h('h3', null, 'Cambios de rol'));
      const d = await S.get('/admin/role-requests?status=PENDING');
      if (!d) return;
      el.append(tbl(['Usuario', 'Acción', 'Rol', 'Motivo', 'Solicitó', 'Fecha', ''], d.requests.map((q) => [q.target, S.label(q.action), S.roleLabel(q.role), q.reason, q.requested_by, fmt(q.created_at),
        can('role:approve') ? h('div', { class: 'actions' }, h('button', { class: 'ok', onclick: () => decide(q, true) }, 'Aprobar'), h('button', { class: 'danger', onclick: () => decide(q, false) }, 'Rechazar')) : ''])));
      if (!d.requests.length) el.append(h('p', { class: 'muted' }, 'No hay solicitudes pendientes.'));
      if (can('role:approve', 'user:read')) {
        const rm = await S.get('/admin/removal-requests?status=PENDING');
        if (rm) {
          el.append(h('h3', null, 'Solicitudes de baja definitiva de usuarios'),
            h('p', { class: 'muted' }, 'Las aprueba el Contralor. La cuenta se conserva desactivada y sin roles para preservar la bitácora y las firmas.'),
            tbl(['Usuario', 'Nombre', 'Justificación', 'Solicitó', 'Fecha', ''], rm.requests.map((q) => [q.target, q.target_name, q.reason, q.requested_by, fmt(q.created_at),
              can('role:approve') ? h('div', { class: 'actions' }, h('button', { class: 'danger', onclick: () => decideRemoval(q, true) }, 'Aprobar baja'), h('button', { class: 'secondary', onclick: () => decideRemoval(q, false) }, 'Rechazar')) : ''])));
        }
      }
    };
    const decideRemoval = async (q, approve) => {
      const v = await S.ask((approve ? 'Aprobar' : 'Rechazar') + ' la baja de ' + q.target, [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }],
        approve ? 'Aprobar baja' : 'Rechazar', approve ? 'La baja es definitiva: la cuenta no podrá reactivarse.' : 'La cuenta queda como está.');
      if (!v) return;
      if (await S.send(`/admin/removal-requests/${q.id}/decision`, 'POST', { approve, note: v.note })) { S.say('Registrado.', true); draw(); }
    };
    const decide = async (q, approve) => {
      const v = await S.ask((approve ? 'Aprobar' : 'Rechazar') + ' solicitud', [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }], approve ? 'Aprobar' : 'Rechazar',
        'No puede resolver una solicitud que usted hizo ni una que le afecte (doble control).');
      if (!v) return;
      if (await S.send(`/admin/role-requests/${q.id}/decision`, 'POST', { approve, note: v.note })) { S.say('Registrado.', true); draw(); }
    };
    draw();
  } });

  // ------------------------------------------------------------------ Reglas de los motores
  // El Administrador del Sistema propone; el Contralor aprueba (doble control). Nada se aplica sin aprobación.
  S.pages.push({ id: 'rules-admin', title: 'Reglas de los motores', perms: ['rule:propose', 'rule:configure'], render: async (el) => {
    const ENGINES = [['SUDEASEG', 'Normativa SUDEASEG'], ['SISTEMAS', 'Auditoría de Sistemas'], ['ANALITICO', 'Motor analítico'],
      ['UNIDAD', 'Unidades y sucursales'], ['CODIFICACION', 'Codificación']];
    const CODE_CATALOGS = [['AUDIT_TYPE', 'Tipo de auditoría'], ['COMPANY', 'Compañía'], ['PLAN_TYPE', 'Siglas (planificada/especial)'],
      ['PROCESS', 'Proceso'], ['FREQUENCY', 'Tipo (frecuencia)'], ['REPORT_COMPANY', 'Compañía del informe']];
    const DOMAINS = [['GENERAL', 'General (operativa)'], ['FINANCIERA', 'Financiera'], ['SISTEMAS', 'Sistemas']];
    let tab = 'SUDEASEG';
    const kwText = (k) => (k || []).join(', ');
    const kwList = (t) => String(t || '').split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Reglas de los motores'),
        h('p', { class: 'muted' }, 'Los cambios los propone el Administrador del Sistema y se aplican solo cuando el Contralor los aprueba. Quien propone no puede aprobar.'));
      const [cat, pend] = await Promise.all([S.get('/rules-admin/catalogs'), S.get('/rules-admin/requests?status=PENDING')]);
      if (!cat || !pend) return;
      el.append(h('div', { class: 'toolbar' }, ENGINES.map(([k, l]) => h('button', { class: k === tab ? '' : 'secondary', onclick: () => { tab = k; draw(); } }, l))));
      if (tab === 'UNIDAD') {
        if (can('rule:propose')) el.append(h('div', { class: 'toolbar' }, h('button', { onclick: () => proposeUnit(null) }, 'Proponer unidad nueva')));
        el.append(tbl(['Código', 'Nombre', 'Tipo', 'Dominio', 'Responsable', 'Activa', ''], cat.unidades.map((r) => [r.key, r.label, r.kind === 'SUCURSAL' ? 'Sucursal' : 'Unidad',
          r.audit_domain, [r.responsible_name, r.responsible_role].filter(Boolean).join(' · ') || '—', r.active ? 'Sí' : 'No',
          can('rule:propose') ? h('button', { class: 'sm', onclick: () => proposeUnit(r) }, 'Proponer cambio') : ''])));
      } else if (tab === 'CODIFICACION') {
        if (can('rule:propose')) el.append(h('div', { class: 'toolbar' }, h('button', { onclick: () => proposeCode(null) }, 'Proponer código nuevo')));
        el.append(tbl(['Catálogo', 'Código', 'Descripción', 'Orden', 'Activo', ''], cat.codificacion.map((r) => [
          (CODE_CATALOGS.find(([k]) => k === r.catalog) || [0, r.catalog])[1], r.code, r.label, r.sort_order, r.active ? 'Sí' : 'No',
          can('rule:propose') ? h('button', { class: 'sm', onclick: () => proposeCode(r) }, 'Proponer cambio') : ''])));
      } else if (tab === 'ANALITICO') {
        el.append(tbl(['Regla', 'Descripción', 'Parámetros vigentes', 'Activa', 'Actualizada', ''], cat.analitico.map((r) => [
          r.key, r.title, h('code', null, JSON.stringify({ ...r.defaults, ...(r.params || {}) })), r.enabled ? 'Sí' : 'No', fmt(r.updated_at),
          can('rule:propose') ? h('button', { class: 'sm', onclick: () => proposeAnalytic(r) }, 'Proponer cambio') : ''])));
      } else {
        const rows = tab === 'SUDEASEG' ? cat.sudeaseg : cat.sistemas;
        if (can('rule:propose')) el.append(h('div', { class: 'toolbar' }, h('button', { onclick: () => proposeCatalog(null) }, 'Proponer regla nueva')));
        el.append(tbl(['Clave', 'Tema', 'Palabras clave', ...(tab === 'SISTEMAS' ? ['Crítico'] : []), 'Orden', 'Activa', 'Actualizada', ''], rows.map((r) => [
          r.key, r.label, h('span', { title: kwText(r.keywords) }, `${(r.keywords || []).length} palabra(s)`), ...(tab === 'SISTEMAS' ? [r.critical ? 'Sí' : 'No'] : []),
          r.sort_order, r.active ? 'Sí' : 'No', fmt(r.updated_at),
          h('div', { class: 'actions' }, h('button', { class: 'sm secondary', onclick: () => showRule(r) }, 'Ver'),
            can('rule:propose') ? h('button', { class: 'sm', onclick: () => proposeCatalog(r) }, 'Proponer cambio') : null)])));
      }
      el.append(h('h3', null, 'Cambios pendientes de aprobación'),
        tbl(['Motor', 'Regla', 'Tipo', 'Motivo', 'Propuso', 'Fecha', ''], pend.requests.map((q) => [
          (ENGINES.find(([k]) => k === q.engine) || [0, q.engine])[1], q.rule_key, q.previous ? 'Cambio' : 'Regla nueva', q.reason, q.requested_by, fmt(q.created_at),
          h('div', { class: 'actions' }, h('button', { class: 'sm secondary', onclick: () => showChange(q) }, 'Ver'),
            can('rule:configure') && q.requested_by !== S.user?.username
              ? [h('button', { class: 'sm ok', onclick: () => decide(q, true) }, 'Aprobar'), h('button', { class: 'sm danger', onclick: () => decide(q, false) }, 'Rechazar')] : null)])));
    };
    const showRule = (r) => {
      const fields = [['Tema', r.label], ['Palabras clave', kwText(r.keywords)], ['Criterio', r.criteria], ['Causa', r.cause], ['Efecto', r.effect],
        ['Recomendación', r.recommendation], ...(r.field_test ? [['Prueba de campo', r.field_test]] : [])];
      const m = S.modal('Regla ' + r.key, h('dl', null, fields.map(([k, v]) => [h('dt', null, k), h('dd', null, v || '—')])));
      m.footer.append(h('button', { onclick: () => m.close() }, 'Cerrar'));
    };
    const showChange = (q) => {
      const keys = Array.from(new Set([...Object.keys(q.previous || {}), ...Object.keys(q.payload || {})]));
      const fmtV = (v) => (Array.isArray(v) ? v.join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : v === true ? 'Sí' : v === false ? 'No' : String(v ?? '—'));
      const changed = keys.filter((k) => JSON.stringify((q.previous || {})[k]) !== JSON.stringify(q.payload[k]));
      const m = S.modal(`${q.engine} · ${q.rule_key}`, h('div', null, h('p', null, h('b', null, 'Motivo: '), q.reason),
        tbl(['Campo', 'Vigente', 'Propuesto'], changed.map((k) => [k, q.previous ? fmtV(q.previous[k]) : '(nueva)', fmtV(q.payload[k])]))));
      m.footer.append(h('button', { onclick: () => m.close() }, 'Cerrar'));
    };
    const proposeCatalog = async (r) => {
      const sys = tab === 'SISTEMAS';
      const v = await S.ask(r ? 'Proponer cambio: ' + r.key : 'Proponer regla nueva', [
        ...(r ? [] : [{ name: 'key', label: 'Clave (minúsculas, números y _; p. ej. nube_privada)', required: true }]),
        { name: 'label', label: 'Tema', value: r?.label, required: true },
        { name: 'keywords', label: 'Palabras clave (separadas por coma)', type: 'textarea', value: kwText(r?.keywords) },
        { name: 'criteria', label: 'Criterio (normativa o estándar aplicable)', type: 'textarea', value: r?.criteria, required: true },
        { name: 'cause', label: 'Causa', type: 'textarea', value: r?.cause, required: true },
        { name: 'effect', label: 'Efecto', type: 'textarea', value: r?.effect, required: true },
        { name: 'recommendation', label: 'Recomendación', type: 'textarea', value: r?.recommendation, required: true },
        ...(sys ? [{ name: 'field_test', label: 'Prueba de campo sugerida', type: 'textarea', value: r?.field_test, required: true },
          { name: 'critical', label: 'Dominio crítico (eleva el riesgo de la evidencia desactualizada)', type: 'checkbox', value: r?.critical }] : []),
        { name: 'sort_order', label: 'Orden (0 a 999)', type: 'number', value: String(r?.sort_order ?? 100) },
        { name: 'active', label: 'Regla activa', type: 'checkbox', value: r ? r.active : true },
        { name: 'reason', label: 'Motivo del cambio (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Proponer',
        'El cambio queda pendiente hasta que el Contralor lo apruebe.');
      if (!v) return;
      const payload = { label: v.label, keywords: kwList(v.keywords), criteria: v.criteria, cause: v.cause, effect: v.effect,
        recommendation: v.recommendation, sort_order: Number(v.sort_order), active: v.active };
      if (sys) Object.assign(payload, { field_test: v.field_test, critical: v.critical });
      const d = await S.send('/rules-admin/requests', 'POST', { engine: tab, rule_key: r ? r.key : v.key, payload, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const proposeUnit = async (r) => {
      const v = await S.ask(r ? 'Proponer cambio: ' + r.key : 'Proponer unidad nueva', [
        ...(r ? [] : [{ name: 'key', label: 'Código (mayúsculas, números y guiones; p. ej. SUC-MARACAY)', required: true }]),
        { name: 'name', label: 'Nombre', value: r?.label, required: true },
        { name: 'kind', label: 'Tipo', type: 'select', value: r?.kind || 'SUCURSAL', options: [['SUCURSAL', 'Sucursal'], ['UNIDAD', 'Unidad administrativa']] },
        { name: 'audit_domain', label: 'Dominio de auditoría', type: 'select', value: r?.audit_domain || 'GENERAL', options: DOMAINS },
        { name: 'responsible_name', label: 'Responsable', value: r?.responsible_name },
        { name: 'responsible_role', label: 'Cargo del responsable', value: r?.responsible_role },
        { name: 'active', label: 'Activa', type: 'checkbox', value: r ? r.active : true },
        { name: 'reason', label: 'Motivo del cambio (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Proponer',
        'Doble verificación: se propone con MFA reciente y se aplica cuando el Contralor lo aprueba.');
      if (!v) return;
      const payload = { name: v.name, kind: v.kind, audit_domain: v.audit_domain, responsible_name: v.responsible_name, responsible_role: v.responsible_role, active: v.active };
      const d = await S.send('/rules-admin/requests', 'POST', { engine: 'UNIDAD', rule_key: (r ? r.key : v.key).toUpperCase(), payload, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const proposeCode = async (r) => {
      const v = await S.ask(r ? `Proponer cambio: ${r.catalog} ${r.code}` : 'Proponer código nuevo', [
        ...(r ? [] : [{ name: 'catalog', label: 'Catálogo', type: 'select', options: CODE_CATALOGS },
          { name: 'code', label: 'Código (1 a 6 letras mayúsculas)', required: true }]),
        { name: 'label', label: 'Descripción', value: r?.label, required: true },
        { name: 'sort_order', label: 'Orden', type: 'number', value: String(r?.sort_order ?? 100) },
        { name: 'active', label: 'Activo (disponible para expedientes e informes nuevos)', type: 'checkbox', value: r ? r.active : true },
        { name: 'reason', label: 'Motivo del cambio (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Proponer',
        'Los códigos ya usados en expedientes e informes no cambian. Doble verificación: MFA y aprobación del Contralor.');
      if (!v) return;
      const key = r ? r.key : `${v.catalog}:${String(v.code).toUpperCase()}`;
      const d = await S.send('/rules-admin/requests', 'POST', { engine: 'CODIFICACION', rule_key: key, payload: { label: v.label, sort_order: Number(v.sort_order), active: v.active }, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const proposeAnalytic = async (r) => {
      const v = await S.ask('Proponer cambio: ' + r.key, [
        { name: 'params', label: 'Parámetros (JSON; solo las claves que cambian respecto de los valores por defecto)', type: 'textarea', value: JSON.stringify(r.params || {}, null, 2) },
        { name: 'enabled', label: 'Regla activa', type: 'checkbox', value: r.enabled },
        { name: 'reason', label: 'Motivo del cambio (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Proponer',
        'Valores por defecto: ' + JSON.stringify(r.defaults));
      if (!v) return;
      let params; try { params = JSON.parse(v.params || '{}'); } catch (_) { S.say('Los parámetros no son un JSON válido.'); return; }
      const d = await S.send('/rules-admin/requests', 'POST', { engine: 'ANALITICO', rule_key: r.key, payload: { params, enabled: v.enabled }, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const decide = async (q, approve) => {
      const v = await S.ask((approve ? 'Aprobar' : 'Rechazar') + ' cambio de regla', [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }],
        approve ? 'Aprobar' : 'Rechazar', approve ? 'El cambio se aplica de inmediato a las próximas observaciones y ejecuciones del motor.' : null);
      if (!v) return;
      if (await S.send(`/rules-admin/requests/${q.id}/decision`, 'POST', { approve, note: v.note })) { S.say('Registrado.', true); draw(); }
    };
    draw();
  } });

  // ------------------------------------------------------------------ Audit trail
  S.pages.push({ id: 'auditlog', title: 'Audit trail', perms: ['auditlog:read'], render: async (el) => {
    el.append(h('h2', null, 'Audit trail (registro inmutable)'));
    const actions = (await S.get('/auditlog/actions'))?.actions || [];
    const f = { action: h('select', null, h('option', { value: '' }, '(todas)'), actions.map((a) => h('option', { value: a }, a))),
      outcome: h('select', null, ['', 'SUCCESS', 'FAILURE', 'DENIED'].map((o) => h('option', { value: o }, o || '(todos)'))),
      actor: h('input', { placeholder: 'usuario' }), desde: h('input', { type: 'date' }), hasta: h('input', { type: 'date' }) };
    const out = h('div');
    let offset = 0;
    const load = async () => {
      const q = new URLSearchParams({ limit: 100, offset });
      for (const [k, v] of Object.entries(f)) if (v.value) q.set(k, v.value);
      const d = await S.get('/auditlog?' + q);
      if (!d) return;
      out.replaceChildren(tbl(['#', 'Fecha', 'Usuario', 'Acción', 'Entidad', 'Resultado', 'IP'], d.events.map((e) => [e.id, fmt(e.occurred_at), e.actor_username || '—', e.action,
        (e.entity_type || '') + (e.entity_id ? ' ' + String(e.entity_id).slice(0, 14) : ''), S.badge(e.outcome), e.ip || ''])),
        h('div', { class: 'row' }, offset ? h('button', { class: 'secondary sm', onclick: () => { offset = Math.max(0, offset - 100); load(); } }, '← Anteriores') : null,
          d.events.length === 100 ? h('button', { class: 'secondary sm', onclick: () => { offset += 100; load(); } }, 'Siguientes →') : null));
    };
    const bar = h('div', { class: 'toolbar' }, h('label', null, 'Acción', f.action), h('label', null, 'Resultado', f.outcome), h('label', null, 'Usuario', f.actor), h('label', null, 'Desde', f.desde), h('label', null, 'Hasta', f.hasta),
      h('button', { onclick: () => { offset = 0; load(); } }, 'Buscar'));
    if (can('auditlog:verify_chain')) bar.append(h('button', { class: 'secondary', onclick: async () => {
      const d = await S.send('/auditlog/verify', 'POST');
      if (d) S.modal('Verificación de integridad', h('div', null, d.ok ? h('div', { class: 'okbox' }, `Cadena íntegra: ${d.rows_checked} eventos verificados, sin inconsistencias.`)
        : h('div', null, h('div', { class: 'warn' }, `¡${d.inconsistencies.length} inconsistencias detectadas!`), S.json(d.inconsistencies)))).footer.append(h('button', { onclick: (e) => e.target.closest('.overlay').remove() }, 'Cerrar'));
    } }, 'Verificar integridad'));
    el.append(bar, out);
    load();
  } });

  // ------------------------------------------------------------------ Sistema
  S.pages.push({ id: 'system', title: 'Sistema', perms: ['health:read', 'param:read', 'backup:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Sistema'));
      if (can('health:read')) {
        const d = await S.get('/admin/system/health');
        if (d) {
          el.append(h('div', { class: 'cards' },
            S.stat(d.database.status === 'ok' ? 'OK' : 'ERROR', 'Base de datos' + (d.database.size_mb ? ` · ${d.database.size_mb} MB · ${d.database.connections} conexiones` : '')),
            S.stat(d.redis.status === 'ok' ? 'OK' : 'ERROR', 'Redis' + (d.redis.queues ? ' · colas: ' + Object.entries(d.redis.queues).map(([k, v]) => k + '=' + v).join(' ') : '')),
            S.stat(d.celery_mode, 'Tareas en segundo plano'), S.stat(d.ingestion_stuck, 'Cargas atascadas (> 10 min)'),
            d.integrity_failures_24h == null ? null : S.stat(d.integrity_failures_24h, 'Fallas de integridad (24 h)')));
        }
      }
      if (can('param:read')) {
        const d = await S.get('/admin/params');
        if (d) el.append(h('h3', null, 'Parámetros'), tbl(['Parámetro', 'Valor', ''], Object.entries(d.params).map(([k, v]) => [k, h('code', null, JSON.stringify(v)),
          can('param:update') ? h('button', { class: 'sm', onclick: () => editParam(k, v) }, 'Editar') : ''])));
      }
      if (can('backup:read')) {
        const d = await S.get('/admin/backups');
        if (d) {
          el.append(h('h3', null, 'Respaldos'), can('backup:run') ? h('div', { class: 'toolbar' }, h('button', { onclick: async () => { if (await S.send('/admin/backups', 'POST')) { S.say('Respaldo solicitado.', true); setTimeout(draw, 3000); } } }, 'Ejecutar respaldo ahora')) : null,
            tbl(['Inicio', 'Estado', 'Tamaño', 'SHA-256', 'Detalle'], d.backups.map((b) => [fmt(b.started_at), S.badge(b.status), b.size_bytes ? (b.size_bytes / 1048576).toFixed(1) + ' MB' : '', (b.sha256 || '').slice(0, 16), b.error || ''])),
            h('p', { class: 'muted' }, 'La restauración no está habilitada desde la aplicación: requiere procedimiento con doble control.'));
        }
      }
    };
    const editParam = async (k, v) => {
      const r = await S.ask('Editar ' + k, [{ name: 'value', label: 'Valor (JSON)', type: 'textarea', value: JSON.stringify(v, null, 2), required: true }], 'Guardar');
      if (!r) return;
      let val; try { val = JSON.parse(r.value); } catch (_) { S.say('El valor no es un JSON válido.'); return; }
      if (await S.send('/admin/params/' + k, 'PUT', { value: val })) { S.say('Parámetro actualizado.', true); draw(); }
    };
    draw();
  } });
})();
