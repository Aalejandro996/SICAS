// SICAS — Evaluación TI de sucursales: resultados de la Evaluación TI de las auditorías operativas cerradas,
// con filtros, criticidad y el informe normativo (SUDEASEG, ISO/IEC 27001:2022 y COBIT 2019). Módulo del Jefe de
// Auditoría de Sistemas; no modifica auditorías.
(() => {
  'use strict';
  const S = window.SICAS, { h, tbl } = S;
  const CRIT = { CRITICA: ['Crítica', 'ALTO'], ALTA: ['Alta', 'ALTO'], MEDIA: ['Media', 'MEDIO'], BAJA: ['Baja', 'BAJO'] };
  const LEVEL = { 1: 'Nivel 1: Óptimo', 2: 'Nivel 2: Satisfactorio', 3: 'Nivel 3: Requiere mejoras', 4: 'Nivel 4: Crítico' };
  const COLOR = { CRITICA: '#c0392b', ALTA: '#e67e22', MEDIA: '#d4a017', BAJA: '#2e8b57' };
  const day = (v) => (v ? new Date(v).toLocaleDateString('es-VE', { timeZone: 'America/Caracas' }) : '—');
  // Fechas sin hora (período del expediente): se muestran tal cual, sin convertir de zona horaria.
  const dateOnly = (v) => (v ? new Date(v).toLocaleDateString('es-VE', { timeZone: 'UTC' }) : '—');
  const pct = (v) => (v == null ? '—' : S.score(v) + '%');
  const critBadge = (c) => (c ? h('span', { class: 'q-risk q-risk-' + CRIT[c][1] }, CRIT[c][0]) : '—');

  // Barras horizontales por sucursal (nota de 0 a 100, color según criticidad).
  const chart = (rows) => {
    const W = 760, bh = 22, gap = 8, left = 170, n = rows.length, H = n * (bh + gap) + 28;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('class', 'ti-chart'); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Nota de la Evaluación TI por sucursal');
    const add = (tag, attrs, text) => { const e = document.createElementNS(svg.namespaceURI, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); if (text != null) e.textContent = text; svg.append(e); return e; };
    const x = (v) => left + (W - left - 60) * (v / 100);
    [0, 25, 50, 75, 100].forEach((t) => { add('line', { x1: x(t), x2: x(t), y1: 0, y2: H - 20, class: 'grid' }); add('text', { x: x(t), y: H - 6, 'text-anchor': 'middle', class: 'axis' }, t + '%'); });
    rows.forEach((r, i) => {
      const y = i * (bh + gap) + 4;
      add('text', { x: left - 8, y: y + bh / 2 + 4, 'text-anchor': 'end', class: 'lbl' }, r.unit_name);
      add('rect', { x: left, y, width: Math.max(2, x(r.score || 0) - left), height: bh, rx: 4, fill: COLOR[r.criticality] || '#8a94a6' });
      add('text', { x: x(r.score || 0) + 6, y: y + bh / 2 + 4, class: 'val' }, `${S.score(r.score)}%${r.sod_conflicts ? ' · SoD' : ''}`);
    });
    return svg;
  };

  async function openDetail(id) {
    const d = await S.get('/ti-branches/' + id);
    if (!d) return;
    const people = (d.detail || {}).people || [], questions = (d.detail || {}).questions || [];
    const m = S.modal(`${d.unit_name} · ${d.audit_code}`, h('div', null,
      h('div', { class: 'cards' }, S.stat(pct(d.score), 'Nota'), S.stat(LEVEL[d.level] || '—', 'Nivel'), S.stat(critBadge(d.criticality), 'Criticidad'),
        S.stat(String(d.collaborators), 'Colaboradores'), S.stat(String(d.sod_conflicts), 'Conflictos de perfiles')),
      h('p', null, h('b', null, 'Dictamen: '), d.dictamen || '—', ' · Cierre: ', day(d.closed_at), ' · Período: ', `${dateOnly(d.period_from)} → ${dateOnly(d.period_to)}`),
      h('h3', null, 'Colaboradores'),
      tbl(['Colaborador', 'Cargo', 'Prácticas (de 15)', 'Nota', 'Nivel', 'Perfiles / SoD', 'Dictamen'], people.map((p) => [p.name, p.role || '—', String(p.yes), pct(p.final),
        LEVEL[p.level] || '—', p.sod.length ? h('span', { class: 'q-risk q-risk-ALTO' }, 'Conflicto: ' + p.sod.map((c) => c.replace('TI-', '')).join(', ')) : 'Sin hallazgos', p.dictamen || '—'])),
      h('h3', null, 'Resultado por pregunta'),
      tbl(['N°', 'Aspecto', 'Sí', 'No', 'Desfavorable', 'ISO/IEC 27001:2022', 'COBIT 2019'], questions.map((q) => [q.number, q.topic, q.yes, q.no, pct(q.fail_rate), q.iso, q.cobit])),
      (d.history || []).length > 1 ? [h('h3', null, 'Evaluaciones anteriores de la sucursal'),
        tbl(['Auditoría', 'Cierre', 'Nota', 'Nivel', 'Conflictos'], d.history.map((x) => [x.audit_code, day(x.closed_at), pct(x.score), LEVEL[x.level] || '—', x.sod_conflicts]))] : null));
    m.overlay.classList.add('wide');
    m.footer.append(h('button', { class: 'secondary', onclick: () => m.close() }, 'Cerrar'));
  }

  S.pages.push({ id: 'ti-branches', title: 'Evaluación TI de sucursales', perms: ['ti_branch:read'], render: async (el) => {
    const f = { from: '', to: '', unit_id: '', criticality: '', sod: '', history: '' };
    const qs = () => Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    const draw = async () => {
      const d = await S.get('/ti-branches' + (qs() ? '?' + qs() : ''));
      if (!d) return;
      const k = d.kpis;
      const input = (name, type) => { const i = h('input', { type, value: f[name] }); i.addEventListener('change', () => { f[name] = i.value; }); return i; };
      const select = (name, opts) => { const s = h('select', null, opts.map(([v, l]) => h('option', { value: v, selected: String(f[name]) === String(v) }, l))); s.addEventListener('change', () => { f[name] = s.value; }); return s; };
      el.replaceChildren(h('div', { class: 'ti-page' }, h('h2', null, 'Evaluación TI de sucursales'),
        h('p', { class: 'muted' }, 'Resultados de la Evaluación TI (ciberseguridad y segregación de funciones) de las auditorías operativas, consolidados al cerrar cada auditoría. ' +
          'Este módulo solo consulta: no modifica las auditorías ni influye en otras evaluaciones.'),
        h('div', { class: 'panel ti-filters' },
          h('label', null, 'Cierre desde', input('from', 'date')), h('label', null, 'Hasta', input('to', 'date')),
          h('label', null, 'Sucursal', select('unit_id', [['', 'Todas'], ...d.branches.map((b) => [b.unit_id, b.unit_name])])),
          h('label', null, 'Criticidad', select('criticality', [['', 'Todas'], ['CRITICA', 'Crítica'], ['ALTA', 'Alta'], ['MEDIA', 'Media'], ['BAJA', 'Baja']])),
          h('label', null, 'Conflictos de perfiles', select('sod', [['', 'Todos'], ['SI', 'Con conflictos'], ['NO', 'Sin conflictos']])),
          h('label', null, 'Evaluaciones', select('history', [['', 'Última de cada sucursal'], ['1', 'Todas (historial)']])),
          h('div', { class: 'toolbar' }, h('button', { onclick: draw }, 'Aplicar filtros'),
            h('button', { class: 'secondary', onclick: () => { Object.keys(f).forEach((x) => { f[x] = ''; }); draw(); } }, 'Limpiar'),
            d.can_report ? h('button', { class: 'ok', onclick: () => S.openFile('/ti-branches/report.pdf' + (qs() ? '?' + qs() : ''), 'Evaluacion_TI_sucursales.pdf', false) },
              'Generar informe (SUDEASEG, ISO 27001, COBIT)') : null)),
        h('div', { class: 'cards' }, S.stat(String(k.branches), 'Sucursales evaluadas'), S.stat(pct(k.avg_score), 'Nota promedio'),
          S.stat(String(k.by_criticality.CRITICA), 'Criticidad crítica'), S.stat(String(k.by_criticality.ALTA), 'Criticidad alta'),
          S.stat(String(k.by_criticality.MEDIA), 'Criticidad media'), S.stat(String(k.by_criticality.BAJA), 'Criticidad baja'),
          S.stat(String(k.with_sod), 'Con conflictos de perfiles'), S.stat(String(k.collaborators), 'Colaboradores')),
        d.rows.length ? h('div', { class: 'panel' }, h('h3', null, 'Nota por sucursal'), chart(d.rows),
          h('div', { class: 'cal-legend' }, ...Object.entries(CRIT).map(([c, [l]]) => h('span', null, h('i', { class: 'sw', style: `background:${COLOR[c]}` }), l))))
          : h('div', { class: 'empty panel' }, 'Todavía no hay evaluaciones TI de auditorías cerradas para estos filtros.'),
        d.rows.length ? [h('h3', null, 'Evaluaciones'),
          tbl(['Sucursal', 'Auditoría', 'Cierre', 'Colaboradores', 'Nota', 'Nivel', 'Criticidad', 'Conflictos SoD', 'Dictamen'], d.rows.map((r) => [r.unit_name, r.audit_code, day(r.closed_at),
            r.collaborators, pct(r.score), LEVEL[r.level] || '—', critBadge(r.criticality), r.sod_conflicts || '0', r.dictamen || '—']), (i) => openDetail(d.rows[i].audit_id))] : null,
        d.questions.length ? [h('h3', null, 'Aspectos con más respuestas desfavorables'),
          tbl(['N°', 'Módulo', 'Aspecto', 'Desfavorable', 'ISO/IEC 27001:2022', 'COBIT 2019'], d.questions.slice(0, 10).map((q) => [q.number, q.module, q.topic, pct(q.fail_rate), q.iso, q.cobit]))] : null));
    };
    draw();
  } });
})();
