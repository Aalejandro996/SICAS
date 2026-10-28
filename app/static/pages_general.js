// SICAS — Informe Ejecutivo (auditorías cerradas por trimestre, semestre o año) e Informe de Documentación (Sistemas:
// auditorías en fase de Documentación). El Auditor lo emite con sus iniciales y lo envía al Jefe de Auditoría; el Jefe
// aprueba (con su firma) o devuelve; aprobado, llega a Gerencia y al Contralor, que firman su recepción.
(() => {
  'use strict';
  const S = window.SICAS, { h, tbl } = S;
  const API = '/general-reports';
  const KIND = { OPERATIVA: 'Operativa', ESPECIAL: 'Especial', ADMINISTRATIVA: 'Administrativa', FINANCIERA: 'Financiera' };
  const REPORT = { EJECUTIVO: 'Informe Ejecutivo', DOCUMENTACION: 'Informe de Documentación' };
  const SITUATION = { CRITICA: ['Crítica', 'ALTO'], ATENCION: ['Requiere atención', 'MEDIO'], ACEPTABLE: ['Aceptable', 'MEDIO'], FAVORABLE: ['Favorable', 'BAJO'], SIN_CALIFICAR: ['Sin calificar', ''] };
  const RISK = { ALTO: ['Alto', 'ALTO'], MEDIO: ['Medio', 'MEDIO'], BAJO: ['Bajo', 'BAJO'] };
  const DOC = { ACTUALIZADA: ['Recibida y actualizada', 'BAJO'], DESACTUALIZADA: ['Recibida, desactualizada', 'MEDIO'], NO_ENTREGADA: ['No entregada', 'ALTO'], SIN_RESPUESTA: ['Sin respuesta', 'ALTO'] };
  const STATUS_CLASS = { DRAFT: 'PENDING', IN_REVIEW: 'IN_REVIEW', RETURNED: 'RETURNED', APPROVED: 'APPROVED' };
  const ACTION = { GENERATED: 'Emitido con las iniciales del Auditor', REGENERATED: 'Datos actualizados', SIGNED_SENT: 'Enviado al Jefe', RETURNED: 'Devuelto',
    APPROVED: 'Aprobado y distribuido', ACKNOWLEDGED: 'Recepción firmada' };
  const PERIOD = { TRIMESTRE: [['1', '1er trimestre'], ['2', '2do trimestre'], ['3', '3er trimestre'], ['4', '4to trimestre']],
    SEMESTRE: [['1', '1er semestre'], ['2', '2do semestre']], ANUAL: [['1', 'Año completo']] };
  const day = (v) => (v ? new Date(v).toLocaleString('es-VE', { timeZone: 'America/Caracas' }) : '—');
  const dateOnly = (v) => (v ? new Date(v).toLocaleDateString('es-VE', { timeZone: 'UTC' }) : '—');
  const pct = (v) => (v == null ? '—' : S.score(v) + '%');
  const chip = (map, k) => (k && map[k] ? h('span', { class: 'q-risk q-risk-' + map[k][1] }, map[k][0]) : 'Pendiente');
  const status = (r) => h('span', { class: 'badge ' + (STATUS_CLASS[r.status] || '') }, r.status_label || r.status);
  const go = (path) => { location.hash = '#/general-reports' + (path ? '/' + path : ''); };

  async function list(el) {
    const d = await S.get(API);
    if (!d) return;
    el.replaceChildren(...[h('h2', null, 'Informe Ejecutivo'),
      h('p', { class: 'muted' }, 'Resume las auditorías cerradas en un trimestre, semestre o año, en un informe de hasta 15 páginas redactado por el motor de reglas ' +
        'con el criterio normativo de la SUDEASEG: un párrafo breve por auditoría y el cuadro de sus hallazgos con el nivel de riesgo. En Sistemas también está el ' +
        'Informe de Documentación (auditorías en fase de Documentación y lo obtenido de la carta). Flujo: el Auditor lo emite con sus iniciales y lo envía al Jefe ' +
        'de Auditoría; el Jefe aprueba (con su firma) o devuelve; aprobado, llega a Gerencia y al Contralor, que firman su recepción.'),
      d.can_create ? h('div', { class: 'toolbar' }, h('button', { onclick: () => go('nuevo') }, 'Nuevo informe')) : null,
      tbl(['Informe', 'Tipo', 'Título', 'Auditorías', 'Estado', 'Elaborado por', 'Actualizado'],
        d.reports.map((r) => [r.code, r.kind_label || REPORT[r.report_kind] || '—', r.title, String(r.audits), status(r), r.created_by_name, day(r.updated_at)]),
        (i) => go(d.reports[i].id))].filter(Boolean));
  }

  async function builder(el) {
    const now = new Date();
    const f = { kind: 'EJECUTIVO', period_type: 'TRIMESTRE', period_n: String(Math.floor(now.getMonth() / 3) + 1), year: String(now.getFullYear()),
      audit_kind: '', unit_id: '', unit_kind: '', q: '' };
    const picked = new Set();
    const qs = () => Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    const title = h('input', { placeholder: 'Opcional: si lo deja vacío se usa «Informe Ejecutivo — tercer trimestre de 2026»', maxlength: 200 });
    const objective = h('textarea', { placeholder: 'Objetivo adicional (opcional): se agrega a los objetivos que redacta el motor de reglas.', maxlength: 600 });
    const results = h('div'), count = h('b', null, '0');
    const paint = () => { count.textContent = String(picked.size); };
    const input = (name, type) => { const i = h('input', { type, value: f[name] }); i.addEventListener('change', () => { f[name] = i.value.trim(); }); return i; };
    const select = (name, opts, onChange) => {
      const s = h('select', null, opts.map(([v, l]) => h('option', { value: v, selected: String(f[name]) === String(v) }, l)));
      s.addEventListener('change', () => { f[name] = s.value; if (onChange) onChange(); });
      return s;
    };
    const nSel = h('select');
    const paintN = () => { nSel.replaceChildren(...PERIOD[f.period_type].map(([v, l]) => h('option', { value: v, selected: v === f.period_n }, l))); if (!PERIOD[f.period_type].some(([v]) => v === f.period_n)) f.period_n = '1'; };
    nSel.addEventListener('change', () => { f.period_n = nSel.value; });
    paintN();
    const years = Array.from({ length: 6 }, (_, i) => String(now.getFullYear() - i)).map((y) => [y, y]);
    const periodBox = h('div', { class: 'ti-filters' },
      h('label', null, 'Período', select('period_type', [['TRIMESTRE', 'Trimestre'], ['SEMESTRE', 'Semestre'], ['ANUAL', 'Anual']], paintN)),
      h('label', null, 'Cuál', nSel), h('label', null, 'Año', select('year', years)));
    const unitSel = select('unit_id', [['', 'Todas']]);
    const kindRow = h('div');
    const intro = h('p', { class: 'muted' });
    const paintKind = () => {
      periodBox.hidden = f.kind !== 'EJECUTIVO';
      intro.textContent = f.kind === 'EJECUTIVO'
        ? 'Solo aparecen sus auditorías (de las que forma parte del equipo) cerradas en el período elegido, según su fecha de cierre.'
        : 'Solo aparecen sus auditorías de Sistemas en fase de Documentación, con lo obtenido de cada control pedido en la carta de solicitud.';
    };
    let units = [];
    const search = async () => {
      const d = await S.get(API + '/candidates?' + qs());
      if (!d) return;
      if (!kindRow.childElementCount && Object.keys(d.kinds).length > 1) {
        kindRow.append(h('label', null, 'Tipo de informe', select('kind', Object.entries(d.kinds), () => { picked.clear(); paint(); paintKind(); search(); })));
      }
      if (!units.length) { units = d.units; unitSel.replaceChildren(...[['', 'Todas'], ...units.map((u) => [u.id, u.name])].map(([v, l]) => h('option', { value: v }, l))); }
      if (!d.audits.length) {
        results.replaceChildren(h('div', { class: 'empty panel' }, f.kind === 'EJECUTIVO'
          ? `No tiene auditorías propias cerradas en el ${d.period?.label || 'período'} con esos filtros.`
          : 'No tiene auditorías propias de Sistemas en fase de Documentación con esos filtros.'));
        return;
      }
      const boxes = d.audits.map((a) => {
        const c = h('input', { type: 'checkbox', checked: picked.has(a.id), 'aria-label': 'Seleccionar ' + a.code });
        c.addEventListener('change', () => { if (c.checked) picked.add(a.id); else picked.delete(a.id); paint(); });
        return c;
      });
      const all = h('input', { type: 'checkbox', 'aria-label': 'Seleccionar todas' });
      all.addEventListener('change', () => { boxes.forEach((c, i) => { c.checked = all.checked; if (all.checked) picked.add(d.audits[i].id); else picked.delete(d.audits[i].id); }); paint(); });
      const exec = f.kind === 'EJECUTIVO';
      const body = h('tbody', null, d.audits.map((a, i) => h('tr', null, h('td', null, boxes[i]), h('td', null, a.code), h('td', null, a.unit_name),
        h('td', null, KIND[a.audit_kind] || (a.audit_domain === 'SISTEMAS' ? 'Sistemas' : a.audit_kind || '—')),
        h('td', null, exec ? dateOnly(a.closed_at) : 'Documentación'), h('td', null, `${dateOnly(a.period_from)} → ${dateOnly(a.period_to)}`))));
      results.replaceChildren(...[h('div', { class: 'tablewrap' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, all), ...['Auditoría', 'Unidad / sucursal', 'Tipo', exec ? 'Cierre' : 'Fase', 'Período revisado'].map((x) => h('th', null, x)))), body)),
        S.paginate(body, 15), h('p', { class: 'muted' }, `${d.audits.length} auditoría(s) encontradas${exec ? ' en el ' + d.period.label : ''}. Máximo ${d.max_audits} por informe.`)].filter(Boolean));
    };
    const generate = h('button', { class: 'ok', onclick: (e) => S.busy(e.target, async () => {
      if (!picked.size) return S.say('Seleccione al menos una auditoría');
      const r = await S.send(API, 'POST', { kind: f.kind, period: { type: f.period_type, n: f.period_n, year: f.year }, title: title.value.trim(),
        objective: objective.value.trim(), audit_ids: [...picked], filters: f });
      if (r) { S.say(`Informe ${r.code} emitido con sus iniciales.`, true); go(r.id); }
    }) }, 'Generar informe');
    paintKind();
    el.replaceChildren(h('div', { class: 'toolbar' }, h('button', { class: 'secondary', onclick: () => go('') }, '← Informes')),
      h('h2', null, 'Nuevo informe'), kindRow, intro, periodBox,
      h('div', { class: 'panel ti-filters' },
        h('label', null, 'Tipo de auditoría', select('audit_kind', [['', 'Todos'], ...Object.entries(KIND)])),
        h('label', null, 'Unidad / sucursal', unitSel),
        h('label', null, 'Clase de unidad', select('unit_kind', [['', 'Todas'], ['SUCURSAL', 'Sucursales'], ['UNIDAD', 'Unidades administrativas']])),
        h('label', null, 'Buscar', input('q', 'search')),
        h('div', { class: 'toolbar' }, h('button', { onclick: () => { picked.clear(); paint(); search(); } }, 'Buscar auditorías'))),
      results,
      h('div', { class: 'panel' }, h('h3', null, 'Datos del informe'), h('label', null, 'Título', title), h('label', null, 'Objetivo adicional', objective),
        h('div', { class: 'toolbar' }, h('span', null, 'Auditorías seleccionadas: ', count), generate)));
    search();
  }

  function executiveContent(b) {
    const k = b.kpis;
    return [h('div', { class: 'cards' }, S.stat(pct(k.avg_score), 'Calificación promedio'), S.stat(String(k.audits), 'Auditorías cerradas'),
      S.stat(String(k.units), 'Unidades / sucursales'), S.stat(String(k.by_situation.CRITICA), 'Situación crítica'),
      S.stat(String(k.by_risk.ALTO), 'Hallazgos de riesgo alto'), S.stat(String(k.observations), 'Hallazgos')),
    h('h3', null, 'Situación por unidad'),
    tbl(['Unidad / sucursal', 'Auditorías', 'Calificación', 'Alto', 'Medio', 'Bajo', 'Situación'],
      b.units.map((u) => [u.unit, u.audits.join(', '), pct(u.score), String(u.by_risk.ALTO), String(u.by_risk.MEDIO), String(u.by_risk.BAJO), chip(SITUATION, u.situation)])),
    h('h3', null, 'Resultados por auditoría'),
    ...b.audits.map((a) => h('div', { class: 'panel' }, ...[h('b', null, `${a.code} · ${a.unit}`), ' ', chip(SITUATION, a.situation),
      h('p', null, a.summary || ''),
      a.observations.length ? tbl(['N°', 'Hallazgo', 'Riesgo'], a.observations.map((o, i) => [String(i + 1), o.title, chip(RISK, o.risk)])) : null].filter(Boolean))),
    h('h3', null, 'Temas normativos (SUDEASEG)'),
    tbl(['Tema', 'Hallazgos', 'Alto', 'Unidades'], b.topics.map((t) => [t.label, String(t.total), String(t.by_risk.ALTO), t.units.join(', ')])),
    h('h3', null, 'Conclusión'), ...b.conclusion.map((c) => h('p', null, c))];
  }

  function documentationContent(b) {
    const k = b.kpis;
    return [h('div', { class: 'cards' }, S.stat(String(k.audits), 'Auditorías'), S.stat(String(k.requested), 'Controles pedidos'),
      S.stat(String(k.received), 'Documentación obtenida'), S.stat(pct(k.rate), 'Porcentaje obtenido'),
      S.stat(String(k.totals.NO_ENTREGADA + k.totals.SIN_RESPUESTA), 'No entregada o sin respuesta')),
    ...b.audits.map((a) => h('div', { class: 'panel' }, h('b', null, `${a.code} · ${a.unit}`), h('p', null, a.summary),
      tbl(['Control', 'Documentación pedida', 'Lo obtenido', 'Adjuntos'], a.letter.map((c) => [c.ref, c.question, chip(DOC, c.status), String(c.documents)])))),
    h('h3', null, 'Conclusión'), ...b.conclusion.map((c) => h('p', null, c))];
  }

  async function detail(el, id) {
    const d = await S.get(`${API}/${id}`);
    if (!d) return;
    const r = d.report, b = r.body, can = d.can, name = REPORT[r.report_kind] || 'Informe';
    const reload = () => detail(el, id);
    const act = (path, json, msg) => async (e) => S.busy(e.target, async () => {
      const x = await S.send(`${API}/${id}/${path}`, 'POST', json || {});
      if (x) { S.say(x.note || msg, true); reload(); }
    });
    const bar = h('div', { class: 'toolbar' }, h('button', { class: 'secondary', onclick: () => go('') }, '← Informes'),
      h('button', { onclick: () => S.openFile(`${API}/${id}/pdf`, r.code + '.pdf') }, 'Ver PDF'));
    if (can.regenerate) bar.append(h('button', { class: 'secondary', onclick: act('regenerate', {}, 'Datos actualizados con la información vigente de las auditorías.') }, 'Actualizar datos'));
    if (can.sign) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      if (!confirm('¿Enviar el informe al Jefe de Auditoría? Queda atado al contenido actual.')) return;
      act('sign')(e);
    } }, 'Enviar al Jefe'));
    if (can.approve) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      const v = await S.ask(`Aprobar ${name.toLowerCase()}`, [{ name: 'comment', type: 'textarea', label: 'Comentario (opcional)' }], 'Aprobar y enviar',
        'Al aprobar se estampa su firma registrada en SICAS y el informe se envía a Gerencia y al Contralor.');
      if (v) act('approve', v)(e);
    } }, 'Aprobar y firmar'));
    if (can.return) bar.append(h('button', { class: 'danger', onclick: async (e) => {
      const v = await S.ask(`Devolver ${name.toLowerCase()}`, [{ name: 'comment', type: 'textarea', label: 'Qué debe corregirse', required: true }], 'Devolver');
      if (v) act('return', v, 'Informe devuelto al Auditor.')(e);
    } }, 'Devolver'));
    if (can.acknowledge) bar.append(h('button', { class: 'ok', onclick: async (e) => {
      const v = await S.ask('Registrar recepción', [{ name: 'note', type: 'textarea', label: 'Nota (opcional)' }], 'Firmar recepción', 'Se estampa su firma registrada en SICAS en la hoja de firmas del informe.');
      if (v) act('acknowledge', v, 'Recepción registrada.')(e);
    } }, 'Firmar recepción'));
    const lastReturn = [...d.events].reverse().find((e) => e.action === 'RETURNED');
    el.replaceChildren(...[bar,
      h('h2', null, `${r.code} — ${r.title}`),
      h('div', { class: 'row' }, status(r), ` ${name} · revisión ${r.revision} · elaborado por ${r.created_by_name} · ${b.audits.length} auditoría(s) · emisión ${b.generated_on}`),
      r.status === 'RETURNED' && lastReturn ? h('div', { class: 'warn' }, `Devuelto por ${lastReturn.actor_name}: ${lastReturn.comment}`) : null,
      ...(r.report_kind === 'DOCUMENTACION' ? documentationContent(b) : executiveContent(b)),
      h('h3', null, 'Recepción (Gerencia y Contralor)'),
      tbl(['Recibido por', 'Rol', 'Fecha', 'Nota'], d.acks.map((a) => [a.name, a.role === 'CONTRALOR' ? 'Contralor' : 'Gerencia', day(a.created_at), a.note || '—'])),
      h('h3', null, 'Bitácora'),
      tbl(['Fecha', 'Acción', 'Por', 'Comentario'], d.events.map((e) => [day(e.created_at), ACTION[e.action] || e.action, `${e.actor_name} (${e.actor_role || '—'})`, e.comment || '—']))].filter(Boolean));
  }

  S.pages.push({
    id: 'general-reports', title: 'Informe Ejecutivo',
    perms: ['general_report:create', 'general_report:review', 'general_report:read_approved'],
    render: async (el, args) => {
      if (args && args[0] === 'nuevo') return builder(el);
      if (args && args[0]) return detail(el, args[0]);
      return list(el);
    },
  });
})();
