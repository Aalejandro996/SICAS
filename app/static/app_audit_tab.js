// SICAS — Pestaña «Aplicativo» de una auditoría de aplicativos: encuestas direccionadas por área, panel por bloque,
// matriz de riesgos (con historial y ajuste del auditor), pruebas técnicas, madurez COBIT/CMMI, trazabilidad y dictamen.
(() => {
  'use strict';
  const S = window.SICAS, { h, tbl } = S;
  const A = '/audits';
  const pct = (v) => (v == null ? '—' : `${Number(v).toFixed(1).replace('.', ',')} %`);
  const LEVEL_CLASS = { 'Crítico': 'HIGH', Alto: 'HIGH', Medio: 'MEDIUM', Bajo: 'LOW' };
  const DIAG_CLASS = { Satisfactorio: 'OK', 'Requiere mejora': 'MEDIUM', 'Crítico': 'HIGH', 'Sin evaluar': 'PENDING' };
  const TEST_LABEL = { CUMPLE: 'Cumple', NO_CUMPLE: 'No cumple', NO_APLICA: 'No aplica', PENDIENTE: 'Pendiente' };
  const TEST_CLASS = { CUMPLE: 'OK', NO_CUMPLE: 'HIGH', NO_APLICA: 'PENDING', PENDIENTE: 'PENDING' };
  const pill = (text, cls) => h('span', { class: 'badge ' + (cls || 'PENDING') }, text);
  const panel = (title, intro, ...kids) => h('section', { class: 'panel' }, h('h3', null, title), intro ? h('p', { class: 'muted' }, intro) : null, ...kids);

  S.appAuditTab = async (el, ctx, reload) => {
    const aid = ctx.aid;
    const d = await S.get(`${A}/${aid}/application`);
    if (!d) { el.replaceChildren(h('p', null, 'No se pudo cargar la evaluación del aplicativo.')); return; }
    const app = d.application, ov = d.overview;
    const refresh = () => (reload ? reload() : S.appAuditTab(el, ctx));

    // ------------------------------------------------ ficha y panel de control
    const ficha = h('div', { class: 'cards' },
      S.stat(ov.total, 'Controles'), S.stat(ov.conformes, 'Conformes'), S.stat(ov.hallazgos, 'Hallazgos'),
      S.stat(pct(ov.cumplimiento_efectivo), 'Cumplimiento efectivo'), S.stat(pct(ov.promedio_general), 'Promedio de la fórmula'),
      S.stat(ov.pendientes, 'Sin responder'));
    const profile = h('p', { class: 'muted' },
      `${app.product || app.name}${app.version ? ' ' + app.version : ''} · ${app.vendor || 'Fabricante no indicado'} · BD ${app.db_engine || '—'} · `
      + `Criticidad ${String(app.criticality || '—').toLowerCase()} · Plantilla: ${app.template_title} · `
      + `RPO ${app.params.rpo_min} min · RTO ${app.params.rto_h} h · conmutación cada ${app.params.failover_months} meses`);
    const opinion = h('div', { class: d.opinion.key === 'FAVORABLE' ? 'okbox' : 'warn' },
      h('strong', null, d.opinion.label), h('p', null, d.opinion.text));

    // ------------------------------------------------ encuestas direccionadas
    const areaRows = d.areas.map((ar) => {
      const last = ar.last_survey;
      const answered = (ov.areas.find((x) => x.area === ar.area) || {}).answered || 0;
      const actions = h('div', { class: 'actions' },
        h('button', { class: 'sm secondary', onclick: (e) => S.busy(e.currentTarget, () => S.openFile(`${A}/${aid}/application/survey/${ar.area}`, `Encuesta_${ar.area}.xlsx`, false)) }, 'Descargar encuesta'));
      return [h('strong', null, ar.label), String(ar.questions), `${answered} de ${ar.questions}`,
        last ? `${last.respondent_name || 'Sin nombre'}${last.respondent_role ? ' · ' + last.respondent_role : ''} · ${S.date(last.answered_on) || S.date(last.imported_at)}` : '—',
        actions];
    });
    const upload = h('input', { type: 'file', accept: '.xlsx' });
    const uploadBtn = h('button', { onclick: (e) => S.busy(e.currentTarget, async () => {
      if (!upload.files[0]) { S.say('Seleccione la encuesta respondida (.xlsx)'); return; }
      const fd = new FormData(); fd.append('file', upload.files[0]);
      const r = await S.upload(`${A}/${aid}/application/survey`, fd);
      if (!r.ok) { S.say(S.err(r)); return; }
      const probs = r.data.problems || [];
      S.say(`Encuesta de ${r.data.area_label}: ${r.data.applied} respuesta(s) aplicada(s).` + (probs.length ? ' Revise: ' + probs.join(' · ') : ''), !probs.length);
      refresh();
    }) }, 'Cargar encuesta respondida');
    const surveys = panel('Encuestas direccionadas por área',
      'Cada área recibe solo sus preguntas, redactadas para quien responde, con la evidencia que debe adjuntar y, cuando aplica, el dato '
      + 'medible (minutos, horas o fecha) que se contrasta con los objetivos del aplicativo. El archivo va firmado: si se altera o es de otra '
      + 'auditoría, se rechaza. Las respuestas se aplican al Levantamiento y el archivo queda como evidencia.',
      tbl(['Área destinataria', 'Preguntas', 'Respondidas', 'Última respuesta recibida', ''], areaRows),
      d.can_survey ? h('div', { class: 'toolbar' }, upload, uploadBtn)
        : h('p', { class: 'muted' }, d.phase === 'LEVANTAMIENTO' ? 'Solo el equipo auditor carga las encuestas.' : 'Las encuestas se cargan en la fase de Levantamiento.'));
    const incons = ov.inconsistencias.length
      ? h('div', { class: 'warn' }, h('strong', null, 'Respuestas inconsistentes con el dato informado'),
        h('ul', null, ov.inconsistencias.map((x) => h('li', null, `${x.code}: ${x.message}`))))
      : null;

    // ------------------------------------------------ cumplimiento por bloque
    const blocks = panel('Cumplimiento por bloque', 'Satisfactorio ≥ 80 % · Requiere mejora ≥ 50 % · Crítico por debajo. Conforme = Sí + evidencia + actualizada.',
      tbl(['Bloque', 'Total', 'Conformes', 'Hallazgos', 'Cumplimiento', 'Promedio', 'Diagnóstico'],
        d.blocks.map((b) => [b.label, String(b.total), String(b.conformes), String(b.hallazgos), pct(b.cumplimiento), pct(b.promedio), pill(b.diagnostico, DIAG_CLASS[b.diagnostico])])));

    // ------------------------------------------------ matriz de riesgos
    const riskRows = d.risks.map((r) => {
      const note = [r.history_reason ? '↻ ' + r.history_reason : null, r.override ? `Ajustado por ${r.override.by_name || 'el auditor'}: ${r.override.reason}` : null].filter(Boolean);
      const actions = h('div', { class: 'actions' });
      if (d.editable) {
        actions.append(h('button', { class: 'sm secondary', onclick: async () => {
          const v = await S.ask(`Ajustar ${r.code}`, [
            { name: 'probability', label: 'Probabilidad (1-5)', type: 'select', options: [1, 2, 3, 4, 5].map((n) => [String(n), String(n)]), value: String(r.probability) },
            { name: 'impact', label: 'Impacto (1-5)', type: 'select', options: [1, 2, 3, 4, 5].map((n) => [String(n), String(n)]), value: String(r.impact) },
            { name: 'reason', label: 'Motivo del ajuste (mínimo 10 caracteres; alimenta al motor)', type: 'textarea', required: true }], 'Guardar ajuste',
            'El ajuste prevalece sobre lo calculado y queda en la bitácora y en la retroalimentación del motor.');
          if (v && await S.send(`${A}/${aid}/application/risks/${r.code}`, 'PUT', { probability: Number(v.probability), impact: Number(v.impact), reason: v.reason })) refresh();
        } }, 'Ajustar'));
        if (r.override) actions.append(h('button', { class: 'sm secondary', onclick: async () => { if (await S.send(`${A}/${aid}/application/risks/${r.code}`, 'PUT', { clear: true })) refresh(); } }, 'Restaurar'));
      }
      return [h('strong', null, r.code), h('div', null, h('div', null, r.category), h('div', { class: 'muted' }, r.description)), r.control,
        `${r.probability}${r.history_delta ? (r.history_delta > 0 ? ' ↑' : ' ↓') : ''}`, String(r.impact), String(r.score), pill(r.level, LEVEL_CLASS[r.level]),
        h('div', null, h('div', null, r.status), note.length ? h('div', { class: 'muted' }, note.join(' · ')) : null), actions];
    });
    const risks = panel('Matriz de riesgos', 'Probabilidad x impacto: ≥ 15 crítico, ≥ 10 alto, ≥ 5 medio. ↑/↓: el motor ajustó la probabilidad por el historial del control en otras auditorías cerradas.',
      tbl(['Riesgo', 'Categoría', 'Control', 'P', 'I', 'P x I', 'Nivel', 'Estatus', ''], riskRows));

    // ------------------------------------------------ pruebas técnicas
    const ts = d.tests_summary;
    const testRows = d.tests.map((t) => {
      const actions = h('div', { class: 'actions' });
      if (d.editable) actions.append(h('button', { class: 'sm secondary', onclick: async () => {
        const v = await S.ask(`${t.code} — ${t.area}`, [
          { name: 'result', label: 'Resultado', type: 'select', options: Object.entries(TEST_LABEL), value: t.result },
          { name: 'detail', label: 'Lo encontrado (obligatorio si no cumple)', type: 'textarea', value: t.detail || '' },
          { name: 'query_used', label: 'Consulta o procedimiento ejecutado', type: 'textarea', value: t.query || '' }], 'Guardar',
          `${t.procedure} Criterio: ${t.criterion} (${t.standard}).`);
        if (v && await S.send(`${A}/${aid}/application/tests/${t.code}`, 'PUT', v)) refresh();
      } }, 'Registrar'));
      return [h('strong', null, t.code), t.program_label, h('div', null, h('div', null, t.area), h('div', { class: 'muted' }, t.procedure)), t.standard,
        pill(TEST_LABEL[t.result], TEST_CLASS[t.result]), t.detail || '—', actions];
    });
    const tests = panel('Pruebas técnicas sustantivas', `Ejecutadas ${ts.executed} de ${ts.total}: ${ts.CUMPLE} cumplen, ${ts.NO_CUMPLE} no cumplen, ${ts.NO_APLICA} no aplican.`,
      tbl(['Prueba', 'Programa', 'Área de evaluación', 'Estándar', 'Resultado', 'Detalle', ''], testRows));

    // ------------------------------------------------ madurez
    const matRows = d.maturity.map((m) => {
      const actions = h('div', { class: 'actions' });
      if (d.editable) {
        actions.append(h('button', { class: 'sm secondary', onclick: async () => {
          const v = await S.ask(m.label, [
            { name: 'level', label: 'Nivel de madurez', type: 'select', options: [0, 1, 2, 3, 4, 5].map((n) => [String(n), `${n} — ${({ 0: 'Inexistente', 1: 'Inicial / Ad-hoc', 2: 'Gestionado', 3: 'Definido', 4: 'Medible', 5: 'Optimizado' })[n]}`]), value: String(m.level ?? m.suggested ?? 0) },
            { name: 'note', label: 'Dictamen técnico del dominio', type: 'textarea', value: m.note || '', required: true }], 'Guardar',
            `Nivel sugerido por el motor: ${m.suggested ?? '—'} (promedio del bloque ${pct(m.average)}).`);
          if (v && await S.send(`${A}/${aid}/application/maturity/${encodeURIComponent(m.key)}`, 'PUT', { level: Number(v.level), note: v.note })) refresh();
        } }, 'Evaluar'));
        if (m.override) actions.append(h('button', { class: 'sm secondary', onclick: async () => { if (await S.send(`${A}/${aid}/application/maturity/${encodeURIComponent(m.key)}`, 'PUT', { clear: true })) refresh(); } }, 'Restaurar'));
      }
      return [m.label, m.level == null ? '—' : String(m.level), m.name, m.state, m.suggested == null ? '—' : String(m.suggested), m.note || '—', actions];
    });
    const maturity = panel('Madurez de los controles de TI (COBIT / CMMI)', 'El motor sugiere el nivel a partir del promedio del bloque; el auditor lo confirma o ajusta con su dictamen técnico.',
      tbl(['Dominio', 'Nivel', 'Nombre', 'Estado', 'Sugerido', 'Dictamen técnico', ''], matRows));

    // ------------------------------------------------ trazabilidad
    const trace = panel('Trazabilidad regulatoria', 'Requisitos normativos vinculados a un control del cuestionario. Las referencias SUDEASEG por validar se confirman con el área legal.',
      tbl(['Código', 'Área', 'Marco regulatorio', 'Requerimiento', 'Control', 'Estado', 'Estándar internacional'],
        d.trace.map((t) => [t.code, t.area, t.framework, t.requirement, t.control, pill(t.state === 'CONFORME' ? 'Conforme' : t.state === 'SIN EVALUAR' ? 'Sin evaluar' : 'Hallazgo', t.state === 'CONFORME' ? 'OK' : t.state === 'SIN EVALUAR' ? 'PENDING' : 'HIGH'), t.international])));

    el.replaceChildren(h('div', { class: 'app-audit' },
      h('section', { class: 'panel' }, h('h3', null, `Aplicativo: ${app.name}`), profile, ficha, opinion),
      surveys, incons, blocks, risks, tests, maturity, trace));
  };
})();
