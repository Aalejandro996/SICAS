// SICAS — Informe general de auditorías: el Auditor consolida las auditorías en fase de Documentación o de Informe,
// firma y envía al Jefe de Auditoría; el Jefe aprueba o devuelve; aprobado, llega a Gerencia y al Contralor.
(() => {
  'use strict';
  const S = window.SICAS, { h, tbl } = S;
  const API = '/general-reports';
  const PHASE = { DOCUMENTACION: 'Documentación', INFORME: 'Informe' };
  const KIND = { OPERATIVA: 'Operativa', ESPECIAL: 'Especial', ADMINISTRATIVA: 'Administrativa', FINANCIERA: 'Financiera' };
  const SITUATION = { CRITICA: ['Crítica', 'ALTO'], ATENCION: ['Requiere atención', 'MEDIO'], ACEPTABLE: ['Aceptable', 'MEDIO'], FAVORABLE: ['Favorable', 'BAJO'], SIN_CALIFICAR: ['Sin calificar', ''] };
  const STATUS_CLASS = { DRAFT: 'PENDING', IN_REVIEW: 'IN_REVIEW', RETURNED: 'RETURNED', APPROVED: 'APPROVED' };
  const ACTION = { GENERATED: 'Emitido con las iniciales del Auditor', REGENERATED: 'Datos actualizados', SIGNED_SENT: 'Enviado al Jefe', RETURNED: 'Devuelto',
    APPROVED: 'Aprobado y distribuido', ACKNOWLEDGED: 'Recepción firmada' };
  const day = (v) => (v ? new Date(v).toLocaleString('es-VE', { timeZone: 'America/Caracas' }) : '—');
  const dateOnly = (v) => (v ? new Date(v).toLocaleDateString('es-VE', { timeZone: 'UTC' }) : '—');
  const pct = (v) => (v == null ? '—' : S.score(v) + '%');
  const sit = (s) => (s ? h('span', { class: 'q-risk q-risk-' + SITUATION[s][1] }, SITUATION[s][0]) : '—');
  const status = (r) => h('span', { class: 'badge ' + (STATUS_CLASS[r.status] || '') }, r.status_label || r.status);
  const go = (path) => { location.hash = '#/general-reports' + (path ? '/' + path : ''); };

  async function list(el) {
    const d = await S.get(API);
    if (!d) return;
    el.replaceChildren(...[h('h2', null, 'Informe general de auditorías'),
      h('p', { class: 'muted' }, 'Consolida las auditorías en fase de Documentación o de Informe en un informe de hasta 15 páginas, redactado por el ' +
        'motor de reglas con el criterio normativo de la SUDEASEG. Flujo: el Auditor lo emite con sus iniciales y lo envía al Jefe de Auditoría; el Jefe aprueba ' +
        '(con su firma) o devuelve; aprobado, llega a Gerencia y al Contralor, que firman su recepción.'),
      d.can_create ? h('div', { class: 'toolbar' }, h('button', { onclick: () => go('nuevo') }, 'Nuevo informe general')) : null,
      tbl(['Informe', 'Título', 'Auditorías', 'Promedio', 'Unidades críticas', 'Estado', 'Elaborado por', 'Actualizado'],
        d.reports.map((r) => [r.code, r.title, String(r.audits), pct(r.avg_score), String((r.by_situation || {}).CRITICA ?? 0), status(r),
          r.created_by_name, day(r.updated_at)]), (i) => go(d.reports[i].id))].filter(Boolean));
  }

  async function builder(el) {
    const f = { phase: '', audit_kind: '', unit_id: '', unit_kind: '', status: '', from: '', to: '', q: '' };
    const picked = new Set();
    const qs = () => Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    const title = h('input', { placeholder: 'Ej.: Estado de las sucursales — tercer trimestre 2026', maxlength: 200 });
    const objective = h('textarea', { placeholder: 'Objetivo adicional (opcional): se agrega a los objetivos que redacta el motor de reglas.', maxlength: 600 });
    const results = h('div'), count = h('b', null, '0');
    const paint = () => { count.textContent = String(picked.size); };
    const input = (name, type) => { const i = h('input', { type, value: f[name] }); i.addEventListener('change', () => { f[name] = i.value.trim(); }); return i; };
    const select = (name, opts) => { const s = h('select', null, opts.map(([v, l]) => h('option', { value: v }, l))); s.addEventListener('change', () => { f[name] = s.value; }); return s; };
    let units = [];

    const search = async () => {
      const d = await S.get(API + '/candidates' + (qs() ? '?' + qs() : ''));
      if (!d) return;
      if (!units.length) { units = d.units; unitSel.replaceChildren(...[['', 'Todas'], ...units.map((u) => [u.id, u.name])].map(([v, l]) => h('option', { value: v }, l))); }
      if (!d.audits.length) { results.replaceChildren(h('div', { class: 'empty panel' }, 'No tiene auditorías propias en fase de Documentación o de Informe con esos filtros.')); return; }
      const boxes = d.audits.map((a) => {
        const c = h('input', { type: 'checkbox', checked: picked.has(a.id), 'aria-label': 'Seleccionar ' + a.code });
        c.addEventListener('change', () => { if (c.checked) picked.add(a.id); else picked.delete(a.id); paint(); });
        return c;
      });
      const all = h('input', { type: 'checkbox', 'aria-label': 'Seleccionar todas' });
      all.addEventListener('change', () => { boxes.forEach((c, i) => { c.checked = all.checked; if (all.checked) picked.add(d.audits[i].id); else picked.delete(d.audits[i].id); }); paint(); });
      const body = h('tbody', null, d.audits.map((a, i) => h('tr', null, h('td', null, boxes[i]), h('td', null, a.code), h('td', null, a.unit_name),
        h('td', null, KIND[a.audit_kind] || (a.audit_domain === 'SISTEMAS' ? 'Sistemas' : a.audit_kind || '—')), h('td', null, PHASE[a.phase] || a.phase),
        h('td', null, a.status === 'CLOSED' ? 'Cerrada' : 'En curso'), h('td', null, `${dateOnly(a.period_from)} → ${dateOnly(a.period_to)}`))));
      results.replaceChildren(...[h('div', { class: 'tablewrap' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, all), ...['Auditoría', 'Unidad / sucursal', 'Tipo', 'Fase', 'Estado', 'Período'].map((x) => h('th', null, x)))), body)),
        S.paginate(body, 15), h('p', { class: 'muted' }, `${d.audits.length} auditoría(s) encontradas. Máximo ${d.max_audits} por informe.`)].filter(Boolean));
    };
    const unitSel = select('unit_id', [['', 'Todas']]);
    const generate = h('button', { class: 'ok', onclick: (e) => S.busy(e.target, async () => {
      if (!picked.size) return S.say('Seleccione al menos una auditoría');
      if (title.value.trim().length < 5) return S.say('Escriba el título del informe (mínimo 5 caracteres)');
      const r = await S.send(API, 'POST', { title: title.value.trim(), objective: objective.value.trim(), audit_ids: [...picked], filters: f });
      if (r) { S.say(`Informe ${r.code} generado.`, true); go(r.id); }
    }) }, 'Generar informe');
    el.replaceChildren(h('div', { class: 'toolbar' }, h('button', { class: 'secondary', onclick: () => go('') }, '← Informes generales')),
      h('h2', null, 'Nuevo informe general'),
      h('p', { class: 'muted' }, 'Solo aparecen sus auditorías (de las que forma parte del equipo) en fase de Documentación o de Informe. Filtre y marque las que desea consolidar.'),
      h('div', { class: 'panel ti-filters' },
        h('label', null, 'Fase', select('phase', [['', 'Documentación e Informe'], ['DOCUMENTACION', 'Documentación'], ['INFORME', 'Informe']])),
        h('label', null, 'Tipo de auditoría', select('audit_kind', [['', 'Todos'], ...Object.entries(KIND)])),
        h('label', null, 'Unidad / sucursal', unitSel),
        h('label', null, 'Clase de unidad', select('unit_kind', [['', 'Todas'], ['SUCURSAL', 'Sucursales'], ['UNIDAD', 'Unidades administrativas']])),
        h('label', null, 'Estado', select('status', [['', 'Todas'], ['IN_PROGRESS', 'En curso'], ['CLOSED', 'Cerradas']])),
        h('label', null, 'Período desde', input('from', 'date')), h('label', null, 'Hasta', input('to', 'date')),
        h('label', null, 'Buscar', input('q', 'search')),
        h('div', { class: 'toolbar' }, h('button', { onclick: search }, 'Aplicar filtros'))),
      results,
      h('div', { class: 'panel' }, h('h3', null, 'Datos del informe'), h('label', null, 'Título', title), h('label', null, 'Objetivo adicional', objective),
        h('div', { class: 'toolbar' }, h('span', null, 'Auditorías seleccionadas: ', count), generate)));
    search();
  }

  async function detail(el, id) {
    const d = await S.get(`${API}/${id}`);
    if (!d) return;
    const r = d.report, b = r.body, k = b.kpis, can = d.can;
    const reload = () => detail(el, id);
    const act = (path, json, msg) => async (e) => S.busy(e.target, async () => {
      const x = await S.send(`${API}/${id}/${path}`, 'POST', json || {});
      if (x) { S.say(x.note || msg, true); reload(); }
    });
    const bar = h('div', { class: 'toolbar' }, h('button', { class: 'secondary', onclick: () => go('') }, '← Informes generales'),
      h('button', { onclick: () => S.openFile(`${API}/${id}/pdf`, r.code + '.pdf') }, 'Ver PDF'));
    if (can.regenerate) bar.append(h('button', { class: 'secondary', onclick: act('regenerate', {}, 'Datos actualizados con la información vigente de las auditorías.') }, 'Actualizar datos'));
    if (can.sign) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      if (!confirm('¿Enviar el informe al Jefe de Auditoría? Queda atado al contenido actual.')) return;
      act('sign')(e);
    } }, 'Enviar al Jefe'));
    if (can.approve) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      const v = await S.ask('Aprobar informe general', [{ name: 'comment', type: 'textarea', label: 'Comentario (opcional)' }], 'Aprobar y enviar',
        'Al aprobar se estampa su firma registrada en SICAS y el informe se envía a Gerencia y al Contralor.');
      if (v) act('approve', v)(e);
    } }, 'Aprobar y firmar'));
    if (can.return) bar.append(h('button', { class: 'danger', onclick: async (e) => {
      const v = await S.ask('Devolver informe general', [{ name: 'comment', type: 'textarea', label: 'Qué debe corregirse', required: true }], 'Devolver');
      if (v) act('return', v, 'Informe devuelto al Auditor.')(e);
    } }, 'Devolver'));
    if (can.acknowledge) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      const v = await S.ask('Registrar recepción', [{ name: 'note', type: 'textarea', label: 'Nota (opcional)' }], 'Firmar recepción', 'Se estampa su firma registrada en SICAS en la hoja de firmas del informe.');
      if (v) act('acknowledge', v, 'Recepción registrada.')(e);
    } }, 'Firmar recepción'));
    const lastReturn = [...d.events].reverse().find((e) => e.action === 'RETURNED');
    el.replaceChildren(...[bar,
      h('h2', null, `${r.code} — ${r.title}`),
      h('div', { class: 'row' }, status(r), ` Revisión ${r.revision} · elaborado por ${r.created_by_name} · ${b.audits.length} auditoría(s) · emisión ${b.generated_on}`),
      r.status === 'RETURNED' && lastReturn ? h('div', { class: 'warn' }, `Devuelto por ${lastReturn.actor_name}: ${lastReturn.comment}`) : null,
      h('div', { class: 'cards' }, S.stat(pct(k.avg_score), 'Calificación promedio'), S.stat(String(k.units), 'Unidades / sucursales'),
        S.stat(String(k.by_situation.CRITICA), 'Situación crítica'), S.stat(String(k.by_situation.ATENCION), 'Requieren atención'),
        S.stat(String(k.by_risk.ALTO), 'Hallazgos de riesgo alto'), S.stat(String(k.observations), 'Hallazgos vigentes')),
      h('h3', null, 'Situación actual por unidad'),
      tbl(['Unidad / sucursal', 'Auditorías', 'Calificación', 'Alto', 'Medio', 'Bajo', 'Situación'],
        b.units.map((u) => [u.unit, u.audits.join(', '), pct(u.score), String(u.by_risk.ALTO), String(u.by_risk.MEDIO), String(u.by_risk.BAJO), sit(u.situation)])),
      h('h3', null, 'Temas normativos (SUDEASEG)'),
      tbl(['Tema', 'Hallazgos', 'Alto', 'Unidades'], b.topics.map((t) => [t.label, String(t.total), String(t.by_risk.ALTO), t.units.join(', ')])),
      h('h3', null, 'Conclusión'), ...b.conclusion.map((c) => h('p', null, c)),
      h('h3', null, 'Auditorías incluidas'),
      tbl(['Auditoría', 'Unidad', 'Fase', 'Calificación', 'Hallazgos', 'Situación'],
        b.audits.map((a) => [a.code, a.unit, PHASE[a.phase] || a.phase, pct(a.score), String(a.observations.length), sit(a.situation)]),
        (i) => { location.hash = '#/audits/' + b.audits[i].id; }),
      h('h3', null, 'Recepción (Gerencia y Contralor)'),
      tbl(['Recibido por', 'Rol', 'Fecha', 'Nota'], d.acks.map((a) => [a.name, a.role === 'CONTRALOR' ? 'Contralor' : 'Gerencia', day(a.created_at), a.note || '—'])),
      h('h3', null, 'Bitácora'),
      tbl(['Fecha', 'Acción', 'Por', 'Comentario'], d.events.map((e) => [day(e.created_at), ACTION[e.action] || e.action, `${e.actor_name} (${e.actor_role || '—'})`, e.comment || '—']))].filter(Boolean));
  }

  S.pages.push({
    id: 'general-reports', title: 'Informe general',
    perms: ['general_report:create', 'general_report:review', 'general_report:read_approved'],
    render: async (el, args) => {
      if (args && args[0] === 'nuevo') return builder(el);
      if (args && args[0]) return detail(el, args[0]);
      return list(el);
    },
  });
})();
