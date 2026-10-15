// SICAS — Auditorías: expedientes, fases, cédulas, observaciones, evidencias, trabajo sin conexión, informes, PAC y firmas.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, fmt } = S;
  const A = '/audits';
  const LINES = [['AUTO', 'Auto'], ['PATRIMONIAL', 'Patrimonial'], ['PERSONAL', 'Personal'], ['ERP_TI', 'ERP / TI']];
  const KINDS = [['SUSCRIPCION', 'Suscripción'], ['RECLAMO', 'Reclamo / indemnización'], ['SISTEMAS', 'Auditoría de Sistemas']];
  const LINE = Object.fromEntries(LINES), KIND = Object.fromEntries(KINDS);
  const PHASES = ['PLANIFICACION', 'TRABAJO_CAMPO', 'INFORME'];
  const RES = [['', '—'], ['CUMPLE', 'Cumple'], ['PARCIAL', 'Parcial'], ['NO_CUMPLE', 'No cumple'], ['NO_APLICA', 'No aplica'], ['EXCEPCION', 'Excepción']];
  const closeBtn = (m, t = 'Cerrar') => h('button', { class: 'secondary', onclick: () => m.close() }, t);
  const dlg = (title, body) => { const m = S.modal(title, body); return m; };

  // Un solo módulo de Auditorías. El dominio visible se determina por los permisos/rol.
  const currentDomain = () => {
    const systems = can('audit:systems_read', 'audit:systems_execute', 'audit:systems_review');
    const financial = can('audit:financial_read', 'audit:financial_execute', 'audit:financial_review');
    if (systems && !financial) return 'SISTEMAS';
    if (financial && !systems) return 'FINANCIERA';
    return null; // Gerencia/Contralor u otros roles con alcance transversal.
  };
  const currentTitle = () => {
    const d = currentDomain();
    return d === 'SISTEMAS' ? 'Auditoría de Sistemas' : d === 'FINANCIERA' ? 'Auditoría Operativa' : 'Auditorías';
  };

  // ================================================================== lista, expedientes, unidades, plantillas
  async function renderList(el, domain = null, title = null) {
    domain = domain || currentDomain();
    title = title || currentTitle();
    el.replaceChildren(h('h2', null, title));
    if (domain) {
      const label = domain === 'FINANCIERA' ? 'OPERATIVA' : 'SISTEMAS / TI';
      el.append(h('div', { class: 'panel' }, h('b', null, `Alcance: ${label}`),
        h('p', { class: 'muted' }, 'Esta pantalla muestra únicamente expedientes y auditorías del dominio asignado a su rol. El control también se aplica en el servidor.')));
    }
    const bar = h('div', { class: 'toolbar' });
    if (can('audit:manage')) bar.append(h('button', { onclick: newFile }, 'Nuevo expediente'), h('button', { onclick: newAudit }, 'Nueva auditoría'));
    if (can('audit:unit_manage')) bar.append(h('button', { class: 'secondary', onclick: units }, 'Unidades y sucursales'));
    if (can('audit:read', 'audit:template_manage')) bar.append(h('button', { class: 'secondary', onclick: templates }, 'Criterios de las cédulas'));
    el.append(bar);
    if (can('audit:read')) {
      const [f, a] = await Promise.all([S.get(A + '/files'), S.get(A)]);
      if (a) el.append(h('h3', null, 'Auditorías'), tbl(['Código', 'Expediente', 'Unidad', 'Modalidad', 'Fase', 'Estado', 'Calificación'], a.audits.map((x) => [x.code, x.file_code, x.unit_name, x.modality, S.label2(x.phase), S.badge(x.status),
        x.manual_score != null ? S.score(x.manual_score) + ' (manual)' : '']), (i) => {
          location.hash = '#/audits/' + a.audits[i].id;
        }));
      if (f) el.append(h('h3', null, 'Expedientes'), tbl(['Código', 'Unidad', 'Título', 'Período', 'Estado', 'Auditorías'], f.files.map((x) => [x.code, x.unit_name, x.title, `${S.date(x.period_from)} → ${S.date(x.period_to)}`, S.badge(x.status), x.audits])));
    }
    if (can('audit:report_approve', 'audit:sign_gerente', 'audit:read_final')) {
      const d = await S.get(A + '/final-reports');
      if (d) el.append(h('h3', null, 'Informes finales'), tbl(['Auditoría', 'Unidad', 'Estado', 'Firmas'], d.reports.map((r) => [r.audit_code, r.unit_name, S.badge(r.status), r.signatures + ' / 2']), (i) => openReport(d.reports[i].id, () => renderList(el))));
    }
  }

  async function newFile() {
    const u = await S.get(A + '/units');
    if (!u) return;
    if (!u.units.length) { S.say('No hay unidades ni sucursales. ' + (can('audit:unit_manage') ? 'Créelas en «Unidades y sucursales».' : 'Pida al Contralor que las registre.')); return; }
    const v = await S.ask('Nuevo expediente', [{ name: 'unit_id', label: 'Unidad / sucursal a auditar', type: 'select', options: u.units.map((x) => [x.id, `${x.name} (${x.code})`]) },
      { name: 'title', label: 'Título del expediente', required: true }, { name: 'objective', label: 'Objetivo general', type: 'textarea' },
      { name: 'period_from', label: 'Período revisado: desde', type: 'date', required: true }, { name: 'period_to', label: 'Período revisado: hasta', type: 'date', required: true }], 'Crear expediente',
      'El expediente se crea primero; luego se abre la auditoría dentro de él.');
    if (!v) return;
    const r = await S.send(A + '/files', 'POST', { ...v, unit_id: Number(v.unit_id) });
    if (r) { S.say('Expediente creado: ' + r.code, true); route(); }
  }

  async function newAudit() {
    const [f, who] = await Promise.all([S.get(A + '/files'), S.get(A + '/auditors')]);
    if (!f || !who) return;
    const open = f.files.filter((x) => x.status === 'OPEN');
    if (!open.length) { S.say('Primero cree el expediente.'); return; }
    const sel = h('select', null, open.map((x) => h('option', { value: x.id }, `${x.code} — ${x.unit_name} — ${x.title}`)));
    const mod = h('select', null, h('option', { value: 'REMOTA' }, 'Remota'), h('option', { value: 'PRESENCIAL' }, 'Presencial'));
    const loc = h('input', { placeholder: 'Lugar (obligatorio si es presencial)' });
    const lines = LINES.filter(([v]) => v !== 'ERP_TI').map(([v, l]) => ({ v, el: h('input', { type: 'checkbox', checked: true }), l }));
    const lineBox = h('div');
    const cn = h('input', { placeholder: 'Responsable de la unidad' });
    const cr = h('input', { placeholder: 'Cargo del responsable' });
    const scopeHint = h('p', { class: 'muted' });
    const sync = () => {
      const file = open.find((x) => x.id === sel.value),
        system = file?.audit_domain === 'SISTEMAS' || can('audit:systems_read') || can('audit:systems_execute') || can('audit:systems_manage') || can('audit:systems_review');
      if (system) {
        lineBox.replaceChildren(h('div', { class: 'panel' }, h('b', null, 'Auditoría de Sistemas'), h('p', { class: 'muted' }, 'No se utilizan líneas Auto, Patrimonial o Personal. El alcance queda asociado a la unidad de Sistemas seleccionada y al cuestionario ERP/TI.')));
      } else {
        lineBox.replaceChildren(h('p', null, 'Líneas en el alcance:'), h('div', { class: 'row' }, lines.map((x) => h('label', null, x.el, ' ', x.l))));
        lines.forEach((x) => { x.el.checked = true; x.el.disabled = false; });
      }
      cn.value = file?.responsible_name || '';
      cr.value = file?.responsible_role || '';
      scopeHint.textContent = system ? 'El cuestionario ERP/TI se prepara automáticamente con los 81 controles oficiales. Puede llenarlo manualmente o cargar el Excel oficial.' : 'Seleccione las líneas que forman parte del alcance.';
    };
    sel.addEventListener('change', sync);
    sync();
    const ta = (ph) => h('textarea', { placeholder: ph });
    const obj = ta('Objetivos de la auditoría'), scope = ta('Alcance'), proc = ta('Procedimientos / metodología (opcional)');
    const ps = h('input', { type: 'date' }), pe = h('input', { type: 'date' });
    const leader = h('select', null, who.auditors.map((a) => h('option', { value: a.id }, a.name)));
    const members = who.auditors.map((a) => ({ a, el: h('input', { type: 'checkbox' }) }));
    const m = dlg('Nueva auditoría', h('div', null,
      h('label', null, 'Expediente', sel), h('label', null, 'Modalidad', mod), h('label', null, 'Lugar', loc),
      lineBox, scopeHint,
      h('label', null, 'Objetivos', obj), h('label', null, 'Alcance', scope), h('label', null, 'Procedimientos', proc),
      h('div', { class: 'toolbar' }, h('label', null, 'Inicio previsto', ps), h('label', null, 'Fin previsto', pe)),
      h('div', { class: 'toolbar' }, h('label', null, 'Responsable de la unidad', cn), h('label', null, 'Cargo', cr)),
      h('label', null, 'Auditor líder', leader), h('p', { class: 'muted' }, 'Otros auditores del equipo (usted debe formar parte):'),
      h('div', { class: 'checklist' }, members.map((x) => h('label', null, x.el, x.a.name)))));
    m.footer.append(closeBtn(m, 'Cancelar'), h('button', { onclick: async () => {
      const file = open.find((x) => x.id === sel.value),
        system = file?.audit_domain === 'SISTEMAS' || can('audit:systems_read') || can('audit:systems_execute') || can('audit:systems_manage') || can('audit:systems_review');
      const body = { file_id: sel.value, modality: mod.value, location: loc.value,
        lines: system ? [] : lines.filter((x) => x.el.checked).map((x) => x.v),
        objectives: obj.value, scope: scope.value, procedures: proc.value, planned_start: ps.value, planned_end: pe.value,
        contact_name: cn.value, contact_role: cr.value, leader_id: leader.value, member_ids: members.filter((x) => x.el.checked).map((x) => x.a.id) };
      const r = await S.send(A, 'POST', body);
      if (r) { m.close(); S.say('Auditoría creada: ' + r.code, true); location.hash = '#/audits/' + r.id + '/cedulas'; }
    } }, 'Crear auditoría'));
  }

  async function units() {
    const draw = async () => {
      const d = await S.get(A + '/units');
      return d ? tbl(['Código', 'Nombre', 'Tipo'], d.units.map((u) => [u.code, u.name, u.kind])) : h('div');
    };
    const holder = h('div', null, await draw());
    const m = dlg('Unidades y sucursales', holder);
    m.footer.append(h('button', { onclick: async () => {
      const v = await S.ask('Nueva unidad', [{ name: 'code', label: 'Código (ej. SUC-01)', required: true }, { name: 'name', label: 'Nombre', required: true }, { name: 'kind', label: 'Tipo', type: 'select', options: [['SUCURSAL', 'Sucursal'], ['UNIDAD', 'Unidad']] }], 'Crear');
      if (v && await S.send(A + '/units', 'POST', v)) holder.replaceChildren(await draw());
    } }, 'Agregar'), closeBtn(m));
  }

  async function templates() {
    const d = await S.get(A + '/templates');
    if (!d) return;
    const m = dlg('Criterios de las cédulas', h('div', null, h('p', { class: 'muted' }, 'Son criterios base genéricos: ajústelos a las cédulas oficiales de la empresa. Cada cédula guarda una copia de los criterios con que se creó, así que cambiarlos no altera auditorías ya iniciadas.'),
      tbl(['Tipo', 'Línea', 'Criterios', 'Versión', ''], d.templates.map((t) => [KIND[t.kind], LINE[t.line], t.criteria.length, t.customized ? 'v' + t.version : 'base',
        can('audit:template_manage') ? h('button', { class: 'sm', onclick: () => editTemplate(t, m) }, 'Editar') : h('button', { class: 'sm secondary', onclick: () => viewTemplate(t) }, 'Ver')]))));
    m.footer.append(closeBtn(m));
  }
  function viewTemplate(t) { const m = dlg(`${KIND[t.kind]} — ${LINE[t.line]}`, tbl(['Código', 'Peso', 'Criterio'], t.criteria.map((c) => [c.code, c.weight, c.text]))); m.footer.append(closeBtn(m)); }
  async function editTemplate(t, parent) {
    const v = await S.ask(`Editar: ${KIND[t.kind]} — ${LINE[t.line]}`, [{ name: 'text', type: 'textarea', required: true, label: 'Un criterio por línea:  CÓDIGO | peso (1, 2 o 3) | texto', value: t.criteria.map((c) => `${c.code} | ${c.weight} | ${c.text}`).join('\n') }], 'Guardar',
      'Peso: 1 normal, 2 importante, 3 crítico. Los códigos deben ser únicos (2 a 6 letras o números).');
    if (!v) return;
    const criteria = [];
    for (const line of v.text.split('\n').map((x) => x.trim()).filter(Boolean)) {
      const p = line.split('|').map((x) => x.trim());
      if (p.length < 3) { S.say('Línea inválida: ' + line); return; }
      criteria.push({ code: p[0], weight: Number(p[1]), text: p.slice(2).join('|') });
    }
    if (await S.send(`${A}/templates/${t.kind}/${t.line}`, 'PUT', { criteria })) { S.say('Criterios actualizados.', true); parent.close(); templates(); }
  }

  // ================================================================== detalle de la auditoría
  let ctx = null;
  async function renderAudit(el, aid, tab) {
    const d = await S.get(`${A}/${aid}`);
    if (!d) { el.replaceChildren(h('p', null, 'No se pudo cargar la auditoría.'), h('a', { href: '#/audits' }, '← Volver')); return; }
    ctx = { d, aid, el, tab: tab || 'resumen', canWrite: d.is_member && d.audit.status === 'IN_PROGRESS' && !d.locked };
    const a = d.audit;
    const body = h('div');
    const tabs = [['resumen', 'Resumen'], ['cedulas', 'Cédulas'], ['observaciones', 'Observaciones'], ['evidencias', 'Evidencias'], ['sinconexion', 'Sin conexión'], ['informes', 'Informes y PAC']];
    el.replaceChildren(h('div', { class: 'row' }, h('a', { href: '#/audits' }, '← Auditorías')),
      h('h2', null, `${a.code} — ${a.unit_name}`),
      h('div', { class: 'row' }, S.badge(a.status), h('span', null, `${a.modality} · ${a.file_code} · ${S.date(a.period_from)} → ${S.date(a.period_to)} · `), S.ratingBadge(d.overall.rating),
        d.overall.final != null ? h('b', null, ' ' + S.score(d.overall.final) + '%') : null, d.locked ? h('span', { class: 'badge PENDING' }, 'Bloqueada: informe en revisión/aprobado') : null),
      h('div', { class: 'tabs' }, tabs.map(([id, t]) => h('button', { class: id === ctx.tab ? 'active' : '', onclick: () => { location.hash = `#/audits/${aid}/${id}`; } }, t))), body);
    ({ resumen, cedulas, observaciones, evidencias, sinconexion, informes })[ctx.tab](body);
  }
  const reload = () => renderAudit(ctx.el, ctx.aid, ctx.tab);

  // ---------------------------------------------------------------- Resumen y fases
  function resumen(el) {
    const { d } = ctx, a = d.audit;
    const sheets = Array.isArray(d.sheets) ? d.sheets : [];
    const phasePos = PHASES.indexOf(a.phase);
    const idx = phasePos < 0 ? 0 : phasePos;
    const phaseLog = Array.isArray(d.phase_log) ? d.phase_log : [];
    const team = Array.isArray(d.team) ? d.team : [];

    const totalItems = sheets.reduce((n, s) => n + Number(s.items || 0), 0);
    const scoredItems = sheets.reduce((n, s) => n + Number(s.scored || 0), 0);
    const exceptions = Number(
      d.overall.exceptions ??
      sheets.reduce((n, s) => n + Number(s.exceptions || 0), 0)
    );
    const completion = totalItems
      ? Math.min(100, Math.round(scoredItems / totalItems * 100))
      : 0;

    const scoreText = (v) => v == null ? 'Pendiente' : `${S.score(v)}%`;
    const scorePct = (v) => v == null
      ? 0
      : Math.min(100, Math.max(0, Number(v) || 0));

    const makeProgress = (value) => {
      const track = h('div', { class: 'audit-progress' });
      const fill = h('span', { class: 'audit-progress-fill' });
      fill.style.width = `${scorePct(value)}%`;
      track.append(fill);
      return track;
    };

    const metric = (label, value, note, tone) =>
      h('div', { class: `audit-kpi ${tone}` },
        h('div', { class: 'audit-kpi-label' }, label),
        h('div', { class: 'audit-kpi-value' }, value),
        h('div', { class: 'audit-kpi-note' }, note)
      );

    const stepper = h('div', { class: 'stepper audit-phase-stepper' },
      PHASES.map((p, i) => h('div', {
        class: 'step ' + (i < idx ? 'done' : i === idx ? 'cur' : '')
      }, `${i + 1}. ${S.label2(p)}`))
    );

    const phaseBtns = h('div', { class: 'row audit-phase-actions' });
    if (ctx.canWrite) {
      if (idx < 2) {
        phaseBtns.append(h('button', {
          onclick: () => movePhase(PHASES[idx + 1])
        }, 'Avanzar a ' + S.label2(PHASES[idx + 1])));
      }
      if (idx > 0) {
        phaseBtns.append(h('button', {
          class: 'secondary',
          onclick: () => movePhase(PHASES[idx - 1])
        }, 'Volver a ' + S.label2(PHASES[idx - 1])));
      }
    }

    const kpis = h('div', { class: 'audit-kpi-grid' });
    kpis.append(
      metric(
        'Calificación final',
        scoreText(d.overall.final),
        d.overall.rating ? S.label2(d.overall.rating) : 'Sin calificación calculada',
        'audit-kpi-blue'
      )
    );

    const controlKpi = metric(
      'Controles calificados',
      `${scoredItems} / ${totalItems}`,
      `${completion}% completado`,
      'audit-kpi-teal'
    );
    controlKpi.append(makeProgress(completion));
    kpis.append(
      controlKpi,
      metric(
        'Excepciones',
        String(exceptions),
        'Información no recibida',
        'audit-kpi-rose'
      ),
      metric(
        'Cédulas',
        String(sheets.length),
        'En esta auditoría',
        'audit-kpi-violet'
      )
    );

    const dataPanel = h('section', { class: 'panel audit-summary-panel' },
      h('h3', null, 'Datos de la auditoría'),
      h('div', { class: 'kv audit-summary-kv' },
        h('b', null, 'Objetivos'), a.objectives || '—',
        h('b', null, 'Alcance'), a.scope || '—',
        h('b', null, 'Procedimientos'), a.procedures || '—',
        h('b', null, 'Líneas'),
        (a.lines || []).map((l) => LINE[l] || l).join(', ') || '—',
        h('b', null, 'Lugar'), a.location || '—',
        h('b', null, 'Colaborador en la unidad'),
        (a.contact_name || '—') + (a.contact_role ? ' · ' + a.contact_role : ''),
        h('b', null, 'Modalidad'), a.modality || '—',
        h('b', null, 'Período'),
        `${S.date(a.period_from) || '—'} → ${S.date(a.period_to) || '—'}`,
        h('b', null, 'Fechas previstas'),
        `${S.date(a.planned_start) || '—'} → ${S.date(a.planned_end) || '—'}`
      )
    );

    const teamPanel = h('section', { class: 'panel audit-summary-panel' },
      h('h3', null, 'Equipo auditor'),
      tbl(
        ['Nombre', 'Rol', 'Iniciales'],
        team.map((t) => [
          t.name,
          t.role === 'LIDER' ? 'Líder' : 'Auditor',
          t.initials || '—'
        ])
      )
    );

    const excellent = d.thresholds?.excelente ?? 90;
    const ratingPanel = h('section', {
      class: 'panel audit-summary-panel audit-rating-panel'
    },
      h('h3', null, 'Calificación global'),
      h('div', { class: 'audit-rating-metrics' },
        h('div', { class: 'audit-rating-metric' },
          h('span', null, 'Automática'),
          h('strong', null, scoreText(d.overall.auto))
        ),
        h('div', { class: 'audit-rating-metric' },
          h('span', null, 'Final'),
          h('strong', null, scoreText(d.overall.final))
        ),
        h('div', { class: 'audit-rating-metric' },
          h('span', null, 'Resultado'),
          S.ratingBadge(d.overall.rating)
        )
      ),
      h('div', { class: 'audit-rating-scale' },
        `Escala: Excelente > ${excellent}; Satisfactorio 70–90; ` +
        'Aceptable 60–69; Necesita mejoras 50–59; No satisfactoria ≤ 49'
      )
    );

    if (a.manual_reason) {
      ratingPanel.append(
        h('p', { class: 'audit-manual-reason' },
          h('b', null, 'Justificación del ajuste: '),
          a.manual_reason
        )
      );
    }

    if (can('audit:rate') && ctx.canWrite && a.phase !== 'PLANIFICACION') {
      ratingPanel.append(
        h('div', { class: 'audit-rating-actions' },
          h('button', {
            class: 'sm',
            onclick: () => manual(
              '/audits/' + a.id + '/rating',
              'Calificación global',
              a.manual_score
            )
          }, 'Ajustar calificación global')
        )
      );
    }

    const resultCards = h('div', { class: 'audit-sheet-results' });
    if (!sheets.length) {
      resultCards.append(
        h('div', { class: 'empty panel' }, 'No hay cédulas registradas.')
      );
    } else {
      sheets.forEach((s) => {
        const result = h('button', {
          class: 'audit-sheet-result',
          type: 'button',
          onclick: () => {
            location.hash = `#/audits/${a.id}/cedulas/${s.id}`;
          }
        });

        result.append(
          h('div', { class: 'audit-sheet-result-head' },
            h('span', { class: 'audit-sheet-result-title' }, s.title || 'Cédula'),
            h('strong', { class: 'audit-sheet-result-score' }, scoreText(s.final))
          ),
          makeProgress(s.final),
          h('div', { class: 'audit-sheet-result-meta' },
            `${Number(s.scored || 0)} de ${Number(s.items || 0)} controles calificados`,
            h('span', null, `${Number(s.exceptions || 0)} excepciones`)
          ),
          S.ratingBadge(s.rating)
        );
        resultCards.append(result);
      });
    }

    const resultsPanel = h('section', {
      class: 'panel audit-summary-panel audit-results-panel'
    },
      h('div', { class: 'audit-section-heading' },
        h('h3', null, 'Resultados por cédula'),
        h('p', { class: 'muted' }, 'Seleccione una cédula para abrir sus controles.')
      ),
      resultCards
    );

    const history = h('details', { class: 'audit-history-details' },
      h('summary', null, `Historial de fases (${phaseLog.length})`),
      tbl(
        ['Fecha', 'De', 'A', 'Usuario', 'Nota'],
        phaseLog.map((p) => [
          fmt(p.changed_at),
          p.from_phase ? S.label2(p.from_phase) : '—',
          S.label2(p.to_phase),
          p.username || '—',
          p.note || '—'
        ])
      )
    );

    const dashboard = h('div', { class: 'audit-summary-dashboard' },
      kpis,
      h('div', { class: 'audit-summary-layout' }, dataPanel, teamPanel),
      ratingPanel,
      resultsPanel,
      history
    );

    el.replaceChildren(stepper, phaseBtns, dashboard);
  }

  async function movePhase(to) {
    const back = PHASES.indexOf(to) < PHASES.indexOf(ctx.d.audit.phase);
    const v = await S.ask('Cambiar de fase: ' + S.label2(to), [{ name: 'note', label: back ? 'Motivo (obligatorio)' : 'Nota (opcional)', type: 'textarea', required: back }], 'Confirmar');
    if (v && await S.send(`${A}/${ctx.aid}/phase`, 'POST', { to, note: v.note })) { S.say('Fase actualizada.', true); reload(); }
  }
  async function manual(path, title, current) {
    const v = await S.ask('Ajuste manual: ' + title, [{ name: 'score', label: 'Calificación manual (0 a 100)', type: 'number', value: current ?? '', required: true }, { name: 'reason', label: 'Justificación (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Aplicar',
      'A criterio del Auditor. Queda registrado con su justificación y se muestra en el informe junto con la nota automática.');
    if (v && await S.send(path, 'PUT', { score: v.score, reason: v.reason })) { S.say('Ajuste aplicado.', true); reload(); }
  }
  async function clearManual(path) { if (confirm('¿Quitar el ajuste manual y volver a la calificación automática?') && await S.send(path, 'PUT', { clear: true })) { S.say('Ajuste eliminado.', true); reload(); } }

  // ---------------------------------------------------------------- Cédulas
  async function cedulas(el) {
    const { d } = ctx;
    if (ctx.sheetId) return sheetView(el, ctx.sheetId);
    const bar = h('div', { class: 'toolbar' });
    if (ctx.canWrite && d.audit.phase !== 'INFORME') bar.append(h('button', { onclick: addSheet }, 'Agregar cédula'));
    const isSys = d.audit.audit_domain === 'SISTEMAS';
    el.append(bar, h('p', { class: 'muted' }, isSys ? 'Cuestionario ERP / TI. Cada fila representa un activo, aplicación, servicio o componente evaluado.' : 'Una cédula por tipo (suscripción o reclamo/indemnización) y línea (Auto, Patrimonial, Personal). Cada fila es una póliza o un siniestro de la muestra.'),
      tbl(['Cédula', 'Criterios', 'Ítems', 'Excepciones', 'Final', 'Calificación'], d.sheets.map((s) => [s.title, s.criteria_count, s.items, s.exceptions, S.score(s.final), S.ratingBadge(s.rating)]), (i) => { location.hash = `#/audits/${ctx.aid}/cedulas/${d.sheets[i].id}`; }));
  }
  async function addSheet() {
    const system = ctx.d.audit.audit_domain === 'SISTEMAS';
    const kinds = system ? [['SISTEMAS', 'Auditoría de Sistemas']] : KINDS.filter(([k]) => k !== 'SISTEMAS');
    const lines = system ? [['ERP_TI', 'ERP / TI']] : LINES.filter(([l]) => ctx.d.audit.lines.includes(l) && l !== 'ERP_TI');
    const v = await S.ask('Agregar cédula', [{ name: 'kind', label: 'Tipo', type: 'select', options: kinds }, { name: 'line', label: 'Línea', type: 'select', options: lines }], 'Crear');
    if (v && await S.send(`${A}/${ctx.aid}/worksheets`, 'POST', v)) { S.say('Cédula creada.', true); reload(); }
  }

  async function sheetView(el, wid) {
    const d = await S.get(`${A}/worksheets/${wid}`);
    if (!d) return;
    const ws = d.worksheet, edit = d.editable && ctx.canWrite;
    const sum = h('span');
    const paint = (s) => sum.replaceChildren(S.ratingBadge(s.rating), ` Final ${S.score(s.final)}%${s.manual_override ? ' (manual)' : ''} · ${s.items} controles · ${s.scored} respondidos`);
    paint(d.summary);
    const bar = h('div', { class: 'toolbar' }, h('button', { class: 'secondary', onclick: () => { location.hash = `#/audits/${ctx.aid}/cedulas`; } }, '← Cédulas'));

    if (ws.kind === 'SISTEMAS') {
      if (edit) {
        const input = h('input', { type: 'file', accept: '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', class: 'hidden' });
        input.addEventListener('change', async () => {
          const file = input.files?.[0];
          if (!file) return;
          const form = new FormData(); form.append('file', file);
          const r = await S.upload(`${A}/worksheets/${wid}/system-questionnaire/import`, form);
          input.value = '';
          if (!r.ok) return S.say(S.err(r));
          S.say(`Excel cargado. ${r.data.statistics.respondidas}/${r.data.statistics.total} controles respondidos.`, true);
          reload();
        });
        bar.append(h('button', { onclick: () => input.click() }, 'Cargar plantilla Excel'), input);
      }
      const st = d.statistics || {};
      const stats = h('div', { class: 'row' },
        S.stat(st.total ?? 0, 'Controles'), S.stat(st.respondidas ?? 0, 'Respondidos'), S.stat(st.controles_si ?? 0, 'Control: Sí'),
        S.stat(st.controles_no ?? 0, 'Control: No'), S.stat(st.controles_documentados ?? 0, 'Documentados'),
        S.stat(st.evidencia_actualizada ?? 0, 'Evidencia actualizada'), S.stat(st.brechas_alto ?? 0, 'Brechas altas'), S.stat(st.brechas_medio ?? 0, 'Brechas medias'));
      const section = h('div', { class: 'panel' }, h('b', null, 'Estadísticas del cuestionario'),
        h('p', { class: 'muted' }, `Cumplimiento: ${S.score(st.cumplimiento)}% · Exposición: ${S.score(st.exposicion)}% · Pendientes: ${st.pendientes ?? 0}`));
      const criteria = Object.fromEntries(ws.criteria.map((c) => [c.code, c]));
      const rows = ws.items.map((it) => systemQuestionRow(it, criteria[it.ref], edit, paint, wid));
      el.append(bar, h('div', { class: 'row' }, sum), stats, section,
        ...(!edit ? [h('div', { class: 'warn' }, d.audit.phase === 'PLANIFICACION' ? 'El cuestionario se califica en Trabajo de campo.' : 'Solo lectura.')] : []),
        h('div', { class: 'grid-wrap audit-system-questionnaire' }, h('table', null, h('thead', null, h('tr', null, ['ID', 'Sección', 'Pregunta de auditoría', 'Existencia', 'Soporte documental', 'Evidencia / entregable', 'Puntaje', 'Observación', ''].map((x) => h('th', null, x)))), h('tbody', null, rows))));
      return;
    }

    if (edit) {
      bar.append(h('button', { onclick: async () => {
        const v = await S.ask('Agregar referencias', [{ name: 'refs', type: 'textarea', label: 'Números de póliza o siniestro (uno por línea)', required: true }], 'Agregar');
        if (v) { const r = await S.send(`${A}/worksheets/${wid}/items`, 'POST', { refs: v.refs.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean) }); if (r) { S.say(r.added + ' ítems agregados.', true); reload(); } }
      } }, 'Agregar referencias'), h('button', { onclick: async () => {
        const v = await S.ask('Muestra aleatoria', [{ name: 'n', type: 'number', label: 'Cantidad de ítems (1 a 200)', value: 20, required: true }], 'Sacar muestra', 'Se toma de las pólizas/siniestros cargados en el período y línea del expediente.');
        if (v) { const r = await S.send(`${A}/worksheets/${wid}/sample`, 'POST', { n: Number(v.n) }); if (r) { S.say(r.added + ' ítems agregados.' + (r.note ? ' ' + r.note : ''), true); reload(); } }
      } }, 'Muestra aleatoria'));
    }
    if (edit && can('audit:rate')) {
      bar.append(h('button', { class: 'secondary', onclick: () => manual(`${A}/worksheets/${wid}/rating`, ws.title, ws.manual_score) }, 'Ajustar nota de la cédula'));
      if (ws.manual_score != null) {
        bar.append(h('button', { class: 'secondary', onclick: () => clearManual(`${A}/worksheets/${wid}/rating`) }, 'Quitar ajuste'));
      }
    }
    const legend = h('details', null, h('summary', null, `Criterios (${ws.criteria.length})`), h('div', { class: 'legend' }, ws.criteria.map((c) => h('div', null, h('b', null, c.code), ` (peso ${c.weight}) `, c.text))));
    const head = ['Referencia', ...ws.criteria.map((c) => h('span', { title: c.text }, c.code)), 'Auto', 'Final', 'Observación del auditor', 'Excepción: información no recibida', ''];
    const rows = ws.items.map((it) => rowFor(it, ws, edit, paint, wid));
    const worksheetContent = [
      bar,
      h('div', { class: 'row' }, sum),
      legend
    ];

    if (ws.manual_reason) {
      worksheetContent.push(
        h('div', { class: 'warn' },
          'Ajuste manual de la cédula: ' + ws.manual_reason)
      );
    }

    if (!edit) {
      worksheetContent.push(
        h('div', { class: 'warn' },
          d.audit.phase === 'PLANIFICACION'
            ? 'La cédula se califica en Trabajo de campo.'
            : 'Solo lectura (no es del equipo, la auditoría está cerrada o el informe quedó bloqueado).')
      );
    }

    worksheetContent.push(
      ws.items.length
        ? h('div', { class: 'grid-wrap audit-financial-worksheet' },
            h('table', null,
              h('thead', null,
                h('tr', null, head.map((x) => h('th', null, x)))),
              h('tbody', null, rows)
            )
          )
        : h('div', { class: 'empty panel' },
            'Sin ítems: agregue referencias o saque una muestra aleatoria.')
    );

    el.append(...worksheetContent);
  }

  function systemQuestionRow(it, criterion, edit, paint, wid) {
    const code = it.ref, cur = (it.results && it.results[code]) || {};
    const state = { results: { [code]: { control: cur.control || '', documental: cur.documental || '', evidencia: cur.evidencia || '' } }, observation: it.observation || '' };
    const auto = h('td'), saving = h('span', { class: 'saving' });
    const setScore = (v) => { auto.textContent = S.score(v); };
    setScore(it.auto_score);
    let timer;
    const save = () => {
      clearTimeout(timer); saving.textContent = 'guardando…';
      timer = setTimeout(async () => {
        const r = await S.call(`${A}/items/${it.id}`, { method: 'PUT', json: state });
        if (!r.ok) { saving.textContent = ''; return S.say(S.err(r)); }
        saving.textContent = 'guardado'; it.auto_score = r.data.auto_score; setScore(r.data.auto_score);
        const fresh = await S.get(`${A}/worksheets/${wid}`); if (fresh) paint(fresh.summary);
      }, 350);
    };
    const select = (key, options) => {
      const sel = h('select', { disabled: !edit }, [['', '—'], ...options].map(([v, l]) => h('option', { value: v, selected: v === state.results[code][key] }, l)));
      sel.addEventListener('change', () => { state.results[code][key] = sel.value; save(); });
      return sel;
    };
    const obs = h('textarea', { disabled: !edit, value: state.observation, placeholder: 'Justificación, evidencia o plan de acción' });
    obs.addEventListener('change', () => { state.observation = obs.value; save(); });
    const actions = h('td', null, saving);
    if (edit && can('audit:rate')) {
      actions.append(h('button', { class: 'sm secondary', onclick: () => manual(`${A}/items/${it.id}/rating`, code, it.manual_score) }, 'Ajustar nota'));
      if (it.manual_score != null) {
        actions.append(h('button', { class: 'sm secondary', onclick: () => clearManual(`${A}/items/${it.id}/rating`) }, 'Quitar'));
      }
    }
    if (edit) actions.append(h('button', { class: 'sm', onclick: () => obsForm({ item_id: it.id, title: '', condition: it.observation || '' }) }, '+ Obs.'));
    return h('tr', null, h('td', null, h('b', null, code)), h('td', null, criterion?.section || '—'), h('td', { title: criterion?.text || '' }, criterion?.text || 'Pregunta no disponible'),
      h('td', null, select('control', [['SI', 'Sí'], ['NO', 'No'], ['PARCIAL', 'Parcialmente']])),
      h('td', null, select('documental', [['SI', 'Sí'], ['NO', 'No']])),
      h('td', null, select('evidencia', [['ACTUALIZADO', 'Actualizado'], ['DESACTUALIZADO', 'Desactualizado'], ['INEXISTENTE', 'Inexistente']])),
      auto, h('td', null, obs), actions);
  }

  function rowFor(it, ws, edit, paint, wid) {
    if (ws.kind === 'SISTEMAS') return systemRowFor(it, ws, edit, paint, wid);
    const state = { results: { ...(it.results || {}) }, observation: it.observation || '', info_exception: it.info_exception || '' };
    const auto = h('td'), fin = h('td'), saving = h('span', { class: 'saving' });
    const setScores = (a, f) => { auto.textContent = S.score(a); fin.replaceChildren(h('b', null, S.score(f)), it.manual_score != null ? h('span', { class: 'badge MEDIUM', title: it.manual_reason || '' }, 'manual') : ''); };
    setScores(it.auto_score, it.final_score);
    let timer;
    const save = () => { clearTimeout(timer); saving.textContent = 'guardando…'; timer = setTimeout(async () => {
      const r = await S.call(`${A}/items/${it.id}`, { method: 'PUT', json: state });
      if (!r.ok) { saving.textContent = ''; S.say(S.err(r)); return; }
      saving.textContent = 'guardado';
      it.auto_score = r.data.auto_score; setScores(r.data.auto_score, it.manual_score != null ? it.manual_score : r.data.auto_score);
      const s = await S.get(`${A}/worksheets/${wid}`); if (s) paint(s.summary);
    }, 450); };
    const cells = ws.criteria.map((c) => {
      const sel = h('select', { disabled: !edit }, RES.map(([v, l]) => h('option', { value: v, selected: v === (state.results[c.code] || '') }, l)));
      const td = h('td', { class: 'res-' + (state.results[c.code] || '') }, sel);
      sel.addEventListener('change', () => {
        if (sel.value) state.results[c.code] = sel.value; else delete state.results[c.code];
        td.className = 'res-' + sel.value; if (sel.value === 'EXCEPCION' && !state.info_exception) exc.focus(); save();
      });
      return td;
    });
    const obs = h('textarea', { disabled: !edit, value: state.observation }), exc = h('textarea', { disabled: !edit, value: state.info_exception, placeholder: 'Qué información no se recibió' });
    obs.addEventListener('change', () => { state.observation = obs.value; save(); });
    exc.addEventListener('change', () => { state.info_exception = exc.value; save(); });
    const actions = h('td', null, saving);
    if (edit && can('audit:rate')) actions.append(h('button', { class: 'sm secondary', onclick: () => manual(`${A}/items/${it.id}/rating`, it.ref, it.manual_score) }, 'Ajustar nota'),
      it.manual_score != null ? h('button', { class: 'sm secondary', onclick: () => clearManual(`${A}/items/${it.id}/rating`) }, 'Quitar') : null);
    if (edit) actions.append(h('button', { class: 'sm', title: 'Crear una observación desde este ítem', onclick: () => obsForm({ item_id: it.id, title: '', condition: it.observation || '' }) }, '+ Obs.'));
    return h('tr', null, h('td', null, h('b', null, it.ref)), cells, auto, fin, h('td', null, obs), h('td', null, exc), actions);
  }

  // ---------------------------------------------------------------- Observaciones
  async function observaciones(el) {
    const d = await S.get(`${A}/${ctx.aid}/observations`);
    if (!d) return;

    const observations = Array.isArray(d.observations) ? d.observations : [];
    const phaseOk = ctx.d.audit.phase !== 'PLANIFICACION';
    const canEdit = Boolean(ctx.canWrite && phaseOk);

    const riskOf = (o) => String(o.risk || 'BAJO').toUpperCase();
    const pacOf = (o) => String(o.pac_status || 'PENDIENTE').toUpperCase();

    const highRisk = (o) => ['ALTO', 'HIGH'].includes(riskOf(o));
    const mediumRisk = (o) => ['MEDIO', 'MEDIUM'].includes(riskOf(o));
    const pendingResponse = (o) => !String(o.unit_decision || '').trim();

    const highCount = observations.filter(highRisk).length;
    const responseCount = observations.filter(pendingResponse).length;
    const pacOpenCount = observations.filter((o) => pacOf(o) !== 'CUMPLIDA').length;

    const riskFilter = h('select', { 'aria-label': 'Filtrar por riesgo' });
    [
      ['', 'Todos los riesgos'],
      ['ALTO', 'Riesgo alto'],
      ['MEDIO', 'Riesgo medio'],
      ['BAJO', 'Riesgo bajo']
    ].forEach(([value, label]) => riskFilter.append(
      h('option', { value }, label)
    ));

    const stateFilter = h('select', { 'aria-label': 'Filtrar por estado' });
    [
      ['', 'Todos los estados'],
      ['SIN_RESPUESTA', 'Sin respuesta de la unidad'],
      ['PAC_PENDIENTE', 'PAC pendiente'],
      ['PAC_EN_CURSO', 'PAC en curso'],
      ['PAC_CUMPLIDA', 'PAC cumplida']
    ].forEach(([value, label]) => stateFilter.append(
      h('option', { value }, label)
    ));

    const search = h('input', {
      type: 'search',
      placeholder: 'Buscar por número u observación',
      'aria-label': 'Buscar observaciones'
    });

    const kpi = (label, value, note, tone) =>
      h('div', { class: `audit-observation-kpi ${tone}` },
        h('span', { class: 'audit-observation-kpi-label' }, label),
        h('strong', { class: 'audit-observation-kpi-value' }, String(value)),
        h('span', { class: 'audit-observation-kpi-note' }, note)
      );

    const header = h('div', { class: 'audit-observations-heading' },
      h('div', null,
        h('h3', null, 'Seguimiento de observaciones'),
        h('p', { class: 'muted' },
          'Consulte hallazgos, respuestas de la unidad y avance del plan de acción correctiva.')
      ),
      h('span', { class: 'audit-observation-total' },
        `${observations.length} registradas`
      )
    );

    const toolbar = h('div', { class: 'toolbar audit-observations-toolbar' });
    if (canEdit) {
      toolbar.append(
        h('button', { onclick: () => obsForm({}) }, 'Nueva observación')
      );
    }

    const kpis = h('div', { class: 'audit-observation-kpis' },
      kpi('Observaciones', observations.length,
        'Total de hallazgos registrados', 'audit-observation-blue'),
      kpi('Riesgo alto', highCount,
        'Hallazgos de mayor prioridad', 'audit-observation-red'),
      kpi('Sin respuesta', responseCount,
        'Pendientes de respuesta de la unidad', 'audit-observation-amber'),
      kpi('PAC por completar', pacOpenCount,
        'Acciones correctivas no cumplidas', 'audit-observation-violet')
    );

    const filters = h('section', { class: 'panel audit-observation-filters' },
      h('label', { class: 'audit-observation-filter' },
        h('span', null, 'Buscar'),
        search
      ),
      h('label', { class: 'audit-observation-filter' },
        h('span', null, 'Nivel de riesgo'),
        riskFilter
      ),
      h('label', { class: 'audit-observation-filter' },
        h('span', null, 'Seguimiento'),
        stateFilter
      )
    );

    const resultCount = h('span', { class: 'audit-observation-total' });
    const tableArea = h('div', { class: 'audit-observations-table' });

    const tablePanel = h('section', {
      class: 'panel audit-observations-panel'
    },
      h('div', { class: 'audit-observations-table-heading' },
        h('div', null,
          h('h3', null, 'Registro de observaciones'),
          h('p', { class: 'muted' },
            'Cada observación conserva su seguimiento y acciones PAC.')
        ),
        resultCount
      ),
      tableArea
    );

    function renderRows() {
      const query = search.value.trim().toLocaleLowerCase('es');
      const selectedRisk = riskFilter.value;
      const selectedState = stateFilter.value;

      const filtered = observations.filter((o) => {
        const risk = riskOf(o);
        const pac = pacOf(o);

        if (selectedRisk) {
          const sameRisk = selectedRisk === 'ALTO'
            ? ['ALTO', 'HIGH'].includes(risk)
            : selectedRisk === 'MEDIO'
              ? ['MEDIO', 'MEDIUM'].includes(risk)
              : ['BAJO', 'LOW'].includes(risk);

          if (!sameRisk) return false;
        }

        if (selectedState === 'SIN_RESPUESTA' && !pendingResponse(o)) {
          return false;
        }
        if (selectedState === 'PAC_PENDIENTE' && pac !== 'PENDIENTE') {
          return false;
        }
        if (selectedState === 'PAC_EN_CURSO' && pac !== 'EN_CURSO') {
          return false;
        }
        if (selectedState === 'PAC_CUMPLIDA' && pac !== 'CUMPLIDA') {
          return false;
        }

        if (query) {
          const searchable = [
            o.seq, o.title, o.condition, o.criteria, o.recommendation,
            o.unit_decision, o.unit_response, o.pac_action, o.pac_owner
          ].filter(Boolean).join(' ').toLocaleLowerCase('es');

          if (!searchable.includes(query)) return false;
        }

        return true;
      });

      resultCount.textContent = `${filtered.length} de ${observations.length}`;

      if (!filtered.length) {
        tableArea.replaceChildren(h('div', { class: 'empty panel' },
          observations.length
            ? 'Ninguna observación coincide con los filtros.'
            : 'Todavía no hay observaciones registradas.'
        ));
        return;
      }

      const decisionLabels = {
        ACEPTA: 'Acepta',
        PARCIAL: 'Acepta parcialmente',
        NO_ACEPTA: 'No acepta'
      };

      const rows = filtered.map((o) => {
        const risk = riskOf(o);
        const pac = pacOf(o);

        const riskType = ['ALTO', 'HIGH'].includes(risk)
          ? 'HIGH'
          : ['MEDIO', 'MEDIUM'].includes(risk) ? 'MEDIUM' : 'LOW';

        const pacType = pac === 'CUMPLIDA'
          ? 'OK'
          : pac === 'EN_CURSO' ? 'PROCESSING' : 'PENDING';

        const actions = h('div', {
          class: 'actions audit-observation-actions'
        });

        if (canEdit) {
          actions.append(
            h('button', {
              class: 'sm',
              onclick: () => obsForm(o)
            }, 'Editar'),
            h('button', {
              class: 'sm secondary',
              onclick: () => obsResponse(o)
            }, 'Respuesta / PAC')
          );
        } else {
          actions.append('Solo lectura');
        }

        return [
          h('strong', null, String(o.seq ?? '—')),
          S.badge(riskType),
          h('div', { class: 'audit-observation-description' },
            h('strong', null, o.title || 'Sin título'),
            o.condition
              ? h('p', { class: 'muted' }, o.condition)
              : null
          ),
          decisionLabels[o.unit_decision] ||
            (o.unit_decision ? S.label2(o.unit_decision) : 'Pendiente'),
          S.badge(pacType),
          S.date(o.pac_due) || '—',
          actions
        ];
      });

      tableArea.replaceChildren(
        tbl(
          ['N.º', 'Riesgo', 'Observación', 'Respuesta de la unidad',
            'Estado PAC', 'Fecha compromiso', 'Acciones'],
          rows
        )
      );
    }

    search.addEventListener('input', renderRows);
    riskFilter.addEventListener('change', renderRows);
    stateFilter.addEventListener('change', renderRows);

    const root = h('div', { class: 'audit-observations-dashboard' },
      header
    );

    if (!phaseOk) {
      root.append(h('div', { class: 'warn' },
        'Las observaciones se registran desde Trabajo de campo.'
      ));
    }

    root.append(toolbar, kpis, filters, tablePanel);
    el.replaceChildren(root);
    renderRows();
  }

  async function obsForm(o) {
    const v = await S.ask(o.id ? 'Editar observación ' + o.seq : 'Nueva observación', [
      { name: 'title', label: 'Título', value: o.title || '', required: true }, { name: 'risk', label: 'Riesgo', type: 'select', options: [['ALTO', 'Alto'], ['MEDIO', 'Medio'], ['BAJO', 'Bajo']].map(([v2, l]) => [v2, l]), value: o.risk || 'MEDIO' },
      { name: 'condition', label: 'Condición (qué se encontró)', type: 'textarea', value: o.condition || '', required: true }, { name: 'criteria', label: 'Criterio (norma o procedimiento incumplido)', type: 'textarea', value: o.criteria || '' },
      { name: 'cause', label: 'Causa', type: 'textarea', value: o.cause || '' }, { name: 'effect', label: 'Efecto / riesgo', type: 'textarea', value: o.effect || '' }, { name: 'recommendation', label: 'Recomendación', type: 'textarea', value: o.recommendation || '' }], 'Guardar');
    if (!v) return;
    const r = o.id ? await S.send(`${A}/observations/${o.id}`, 'PUT', v) : await S.send(`${A}/${ctx.aid}/observations`, 'POST', { ...v, item_id: o.item_id });
    if (r) { S.say('Guardado.', true); if (ctx.tab === 'observaciones') reload(); }
  }
  async function obsResponse(o) {
    const v = await S.ask('Respuesta de la unidad y PAC — observación ' + o.seq, [
      { name: 'unit_decision', label: 'Respuesta de la unidad', type: 'select', options: [['', '(sin respuesta)'], ['ACEPTA', 'Acepta'], ['PARCIAL', 'Acepta parcialmente'], ['NO_ACEPTA', 'No acepta']], value: o.unit_decision || '' },
      { name: 'unit_response', label: 'Comentario de la unidad', type: 'textarea', value: o.unit_response || '' }, { name: 'unit_response_at', label: 'Fecha de la respuesta', type: 'date', value: S.date(o.unit_response_at) },
      { name: 'pac_action', label: 'Acción correctiva (PAC)', type: 'textarea', value: o.pac_action || '' }, { name: 'pac_owner', label: 'Responsable', value: o.pac_owner || '' },
      { name: 'pac_due', label: 'Fecha compromiso', type: 'date', value: S.date(o.pac_due) }, { name: 'pac_status', label: 'Estatus del PAC', type: 'select', options: [['PENDIENTE', 'Pendiente'], ['EN_CURSO', 'En curso'], ['CUMPLIDA', 'Cumplida']], value: o.pac_status || 'PENDIENTE' }], 'Guardar',
      'Registre aquí lo que responda la unidad (por el canal que use) y el PAC acordado.');
    if (v && await S.send(`${A}/observations/${o.id}`, 'PUT', v)) { S.say('Guardado.', true); reload(); }
  }

  // ---------------------------------------------------------------- Evidencias
  async function evidencias(el) {
    const [d, ob] = await Promise.all([S.get(`${A}/${ctx.aid}/evidence`), S.get(`${A}/${ctx.aid}/observations`)]);
    if (!d) return;
    if (ctx.canWrite) {
      const file = h('input', { type: 'file' }), desc = h('input', { placeholder: 'Descripción (qué demuestra)' });
      const obsSel = h('select', null, h('option', { value: '' }, '(sin observación)'), (ob?.observations || []).map((o) => h('option', { value: o.id }, `${o.seq}. ${o.title}`)));
      el.append(h('div', { class: 'panel' }, h('div', { class: 'toolbar' }, h('label', null, 'Archivo', file), h('label', null, 'Descripción', desc), h('label', null, 'Asociar a', obsSel),
        h('button', { onclick: (e) => S.busy(e.target, async () => {
          if (!file.files[0]) { S.say('Seleccione un archivo.'); return; }
          const fd = new FormData(); fd.append('file', file.files[0]); fd.append('description', desc.value); if (obsSel.value) fd.append('observation_id', obsSel.value);
          const r = await S.upload(`${A}/${ctx.aid}/evidence`, fd);
          if (!r.ok) { S.say(S.err(r)); return; }
          S.say('Evidencia registrada con su huella SHA-256.', true); reload();
        }) }, 'Adjuntar')), h('p', { class: 'muted' }, 'PDF, imágenes (PNG/JPG), Word/Excel (.docx/.xlsx), CSV, TXT o correo (.eml). Máximo 25 MB. Las evidencias no se pueden borrar ni reemplazar.')));
    }
    el.append(tbl(['N°', 'Archivo', 'Descripción', 'Tamaño', 'Huella SHA-256', 'Subió', 'Fecha', ''], d.evidence.map((e, i) => [i + 1, e.filename, e.description || '', (e.size_bytes / 1024).toFixed(0) + ' KB', e.sha256.slice(0, 12) + '…', e.uploaded_by, fmt(e.uploaded_at),
      h('button', { class: 'sm', onclick: () => S.openFile(`${A}/evidence/${e.id}/download`, e.filename, false) }, 'Descargar')])));
  }

  // ---------------------------------------------------------------- Trabajo sin conexión
  async function sinconexion(el) {
    const out = h('div'), file = h('input', { type: 'file', accept: '.xlsx' });
    el.append(h('div', { class: 'panel' }, h('h3', null, 'Trabajar fuera de la oficina'),
      h('ol', null, h('li', null, 'Con conexión, descargue el paquete de trabajo (Excel) con sus cédulas y muestras.'), h('li', null, 'Trabaje sin conexión en el Excel: califique cada criterio, anote observaciones y excepciones de información.'),
        h('li', null, 'Al volver a tener conexión, cárguelo aquí. Verá una vista previa de lo que cambiará antes de aplicarlo.')),
      ctx.canWrite && ctx.d.audit.phase !== 'PLANIFICACION' ? h('div', { class: 'toolbar' }, h('button', { onclick: () => S.openFile(`${A}/${ctx.aid}/offline-template`, `SICAS_${ctx.d.audit.code}_sin_conexion.xlsx`, false) }, 'Descargar paquete de trabajo (.xlsx)'))
        : h('div', { class: 'warn' }, 'Disponible para el equipo auditor desde Trabajo de campo, con cédulas creadas.'),
      h('p', { class: 'muted' }, 'El archivo está firmado por el servidor: si se altera su estructura o los identificadores, se rechaza. Las evidencias (fotos y documentos) se adjuntan en la pestaña Evidencias al conectarse.')));
    if (ctx.canWrite && ctx.d.audit.phase !== 'PLANIFICACION') el.append(h('div', { class: 'panel' }, h('h3', null, 'Cargar el paquete trabajado'), h('div', { class: 'toolbar' }, h('label', null, 'Archivo .xlsx', file),
      h('button', { onclick: (e) => S.busy(e.target, () => preview(false)) }, 'Ver vista previa')), out));
    const preview = async (apply, overwrite) => {
      if (!file.files[0]) { S.say('Seleccione el archivo.'); return; }
      const fd = new FormData(); fd.append('file', file.files[0]); fd.append('dry_run', apply ? '0' : '1'); fd.append('overwrite', overwrite ? '1' : '0');
      const r = await S.upload(`${A}/${ctx.aid}/offline-import`, fd);
      if (!r.ok) { out.replaceChildren(h('div', { class: 'warn' }, S.err(r))); return; }
      if (!r.data.dry_run) { S.say(`Importación aplicada: ${r.data.applied} filas.`, true); out.replaceChildren(h('div', { class: 'okbox' }, `Se aplicaron ${r.data.applied} cambios.`)); return; }
      const s = r.data.summary;
      const ow = h('input', { type: 'checkbox' });
      out.replaceChildren(h('div', { class: 'cards' }, S.stat(s.UPDATE, 'Se actualizarán'), S.stat(s.NEW, 'Ítems nuevos'), S.stat(s.UNCHANGED, 'Sin cambios'), S.stat(s.CONFLICT, 'Conflictos'), S.stat(s.INVALID, 'Inválidas')),
        r.data.problems.length ? h('div', { class: 'warn' }, r.data.problems.join(' ')) : null,
        tbl(['Hoja', 'Fila', 'Referencia', 'Resultado', 'Detalle'], r.data.preview.map((p) => [p.sheet, p.row, p.ref, p.status, p.detail])),
        s.CONFLICT ? h('label', null, ow, ' Sobrescribir también los conflictos (el servidor cambió después de la descarga)') : null,
        s.INVALID || r.data.problems.length ? h('div', { class: 'warn' }, 'Hay filas inválidas: corrija el Excel y vuelva a cargarlo.') : h('div', { class: 'row' }, h('button', { class: 'ok', onclick: (e) => S.busy(e.target, () => preview(true, ow.checked)) }, `Aplicar ${s.UPDATE + s.NEW} cambios`)));
    };
  }

  // ---------------------------------------------------------------- Informes y PAC
  async function informes(el) {
    const d = await S.get(`${A}/${ctx.aid}/reports`);
    if (!d) return;
    const a = ctx.d.audit, bar = h('div', { class: 'toolbar' });
    const gen = (kind) => async () => { const r = await S.send(`${A}/${ctx.aid}/reports`, 'POST', { kind }); if (r) { S.say('Informe generado automáticamente.', true); reload(); } };
    if (ctx.d.is_member && a.status === 'IN_PROGRESS' && can('audit:report_draft') && !ctx.d.locked) {
      if (a.phase !== 'PLANIFICACION') bar.append(h('button', { onclick: gen('PREVIO') }, 'Generar informe previo (hacia la unidad)'));
      if (a.phase === 'INFORME') bar.append(h('button', { onclick: gen('FINAL') }, 'Generar informe final'));
    }
    el.append(bar, a.phase !== 'INFORME' ? h('div', { class: 'warn' }, 'El informe final se genera en la fase Informe. El informe previo puede generarse desde Trabajo de campo.') : null,
      tbl(['Tipo', 'Versión', 'Estado', 'Generó', 'Creado', 'Enviado / aprobado'], d.reports.map((r) => [r.kind === 'PREVIO' ? 'Previo' : 'Final', 'v' + r.version, S.badge(r.status), r.created_by_name, fmt(r.created_at),
        r.sent_to ? 'Enviado a ' + r.sent_to : r.approved_by_name ? 'Aprobó ' + r.approved_by_name : '']), (i) => openReport(d.reports[i].id, reload)),
      h('div', { class: 'panel' }, h('h3', null, 'PAC — Plan de Acción Correctiva (anexo en Excel)'),
        h('p', { class: 'muted' }, 'Contiene las observaciones y los campos que completa la unidad. El envío se habilita cuando el informe final está firmado por el Contralor y el Gerente de Control Interno; al enviarlo se cierra la auditoría.'),
        h('div', { class: 'row' }, h('button', { class: 'secondary', onclick: () => S.openFile(`${A}/${ctx.aid}/pac.xlsx`, `PAC_${a.code}.xlsx`, false) }, 'Descargar PAC (.xlsx)'),
          ctx.d.is_member && can('audit:pac_send') && a.status === 'IN_PROGRESS' && d.reports.some((r) => r.kind === 'FINAL' && r.status === 'SIGNED') ? h('button', { class: 'ok', onclick: sendPac }, 'Enviar PAC a la unidad y cerrar') : null),
        a.pac_sent_at ? h('div', { class: 'okbox' }, `PAC enviado a ${a.pac_sent_to} el ${fmt(a.pac_sent_at)}. Auditoría cerrada.`) : null));
  }
  async function sendPac() {
    const v = await S.ask('Enviar PAC a la unidad', [{ name: 'to', label: 'Destinatario (nombre y, para envío automático, correo)', placeholder: 'Nombre Apellido <correo@empresa.com>', required: true }], 'Enviar y cerrar');
    if (!v) return;
    const r = await S.send(`${A}/${ctx.aid}/pac/send`, 'POST', v);
    if (r) { S.say(r.note || 'PAC enviado.', true); reload(); }
  }

  // ---------------------------------------------------------------- Informe: vista, firmas y revisión
  async function openReport(rid, after) {
    const d = await S.get(`${A}/reports/${rid}`);
    if (!d) return;
    const r = d.report, b = r.body, c = d.can;
    const done = () => { if (after) after(); };
    const reopen = (m) => { m.close(); openReport(rid, after); };
    const content = h('div', null,
      h('div', { class: 'kv' }, h('b', null, 'Tipo'), r.kind === 'PREVIO' ? 'Informe previo (hacia la unidad)' : 'Informe final', h('b', null, 'Versión'), 'v' + r.version, h('b', null, 'Estado'), S.badge(r.status),
        h('b', null, 'Calificación'), [S.ratingBadge(b.overall.rating), ' ', b.overall.final != null ? S.score(b.overall.final) + '%' : ''], h('b', null, 'Observaciones'), String((b.observations || []).length),
        h('b', null, 'Limitaciones al alcance'), String((b.limitations || []).length), h('b', null, 'Ajustes manuales'), String((b.adjustments || []).length), r.sent_to ? [h('b', null, 'Enviado a'), r.sent_to] : null),
      r.status === 'RETURNED' ? h('div', { class: 'warn' }, 'Devuelto por el Contralor: revise los comentarios, regenere y vuelva a enviar.') : null,
      r.kind === 'FINAL' ? h('div', null, h('h3', null, 'Firmas'), h('div', { class: 'kv' },
        h('b', null, 'Iniciales auditores'), d.team.map((t) => (d.signoffs.some((s) => s.signer_type === 'AUDITOR_INICIALES' && s.user_id === t.user_id && s.body_sha256 === r.body_sha256) ? '✔ ' : '✘ ') + t.initials + ' ').join('  '),
        h('b', null, 'Colaborador'), (d.signoffs.filter((s) => s.signer_type === 'COLABORADOR').slice(-1)[0]?.display) || (b.contact.name ? b.contact.name + ' (de la auditoría)' : 'sin registrar (firma manuscrita en la impresión)'),
        h('b', null, 'Contralor'), d.signatures.find((x) => x.signer_role === 'CONTRALOR') ? '✔ firmado ' + fmt(d.signatures.find((x) => x.signer_role === 'CONTRALOR').signed_at) : 'pendiente',
        h('b', null, 'Gerente de Control Interno'), d.signatures.find((x) => x.signer_role === 'GERENTE_CI') ? '✔ firmado ' + fmt(d.signatures.find((x) => x.signer_role === 'GERENTE_CI').signed_at) : 'pendiente')) : null,
      h('h3', null, 'Conclusión'), h('p', null, b.conclusion), b.conclusion_custom ? h('span', { class: 'muted' }, '(redactada por el auditor)') : h('span', { class: 'muted' }, '(generada automáticamente)'),
      r.kind === 'FINAL' ? h('div', null, h('h3', null, 'Revisión Auditor ↔ Contralor'), h('div', { class: 'thread' }, d.comments.length ? d.comments.map((x) => h('div', { class: 'c' }, h('b', null, `${x.full_name} (${x.kind.toLowerCase()}) `), h('span', { class: 'muted' }, fmt(x.created_at)), h('div', null, x.text))) : h('span', { class: 'muted' }, 'Sin comentarios'))) : null);
    const m = dlg(`${r.kind === 'PREVIO' ? 'Informe previo' : 'Informe final'} v${r.version}`, content);
    const btn = (label, cls, fn) => h('button', { class: cls || '', onclick: async (e) => { e.target.disabled = true; try { await fn(); } finally { e.target.disabled = false; } } }, label);
    const post = (label, path, cls, body) => btn(label, cls, async () => { const x = await S.send(`${A}/reports/${rid}/${path}`, 'POST', body || {}); if (x) { S.say(x.note || 'Hecho.', true); done(); reopen(m); } });
    m.footer.append(btn(
      r.status === 'SIGNED' || r.status === 'APPROVED' ? 'Abrir / imprimir PDF' :
      r.status === 'CONTRALOR' ? 'Ver PDF firmado por Gerencia' :
      'Vista previa PDF (con marca de agua)',
      'secondary', () => S.openFile(`${A}/reports/${rid}/pdf`, 'informe.pdf')
    ));
    if (c.edit) m.footer.append(post('Regenerar con los datos actuales', 'regenerate', 'secondary'), btn('Editar conclusión', 'secondary', async () => {
      const v = await S.ask('Conclusión del informe', [{ name: 'conclusion', label: 'Texto (déjelo vacío para volver a la conclusión automática)', type: 'textarea', value: b.conclusion }], 'Guardar', 'Cambiar el contenido anula las iniciales ya estampadas.');
      if (v) { const x = await S.send(`${A}/reports/${rid}/regenerate`, 'POST', { conclusion: v.conclusion }); if (x) { done(); reopen(m); } }
    }), btn('Colaborador de la unidad', 'secondary', async () => {
      const v = await S.ask('Colaborador de la unidad auditada', [{ name: 'name', label: 'Nombre', required: true }, { name: 'role', label: 'Cargo', required: true }, { name: 'physical', label: 'Firmará físicamente en la impresión', type: 'checkbox', value: true }], 'Registrar');
      if (v && await S.send(`${A}/reports/${rid}/collaborator`, 'POST', v)) { done(); reopen(m); }
    }));
    if (c.initial) m.footer.append(post('Estampar mis iniciales', 'initial', 'secondary'));
    if (c.submit) m.footer.append(post('Enviar al Jefe de Auditoría', 'submit'));
    if (c.send_previo) m.footer.append(btn('Enviar a la unidad', '', async () => {
      const v = await S.ask('Enviar informe previo', [{ name: 'to_name', label: 'Destinatario en la unidad', required: true }, { name: 'to_email', label: 'Correo (opcional, para envío automático)', type: 'email' }], 'Enviar');
      if (v) { const x = await S.send(`${A}/reports/${rid}/send-previo`, 'POST', v); if (x) { S.say(x.note || 'Enviado.', true); done(); reopen(m); } }
    }));
    if (c.comment) m.footer.append(btn('Comentar', 'secondary', async () => {
      const v = await S.ask('Comentario', [{ name: 'text', label: 'Texto', type: 'textarea', required: true }], 'Publicar');
      if (v && await S.send(`${A}/reports/${rid}/comments`, 'POST', v)) reopen(m);
    }));
    if (c.review) m.footer.append(btn('Devolver al auditor', 'danger', async () => {
      const v = await S.ask('Devolver el informe', [{ name: 'comment', label: 'Qué debe corregirse (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Devolver');
      if (v && await S.send(`${A}/reports/${rid}/return`, 'POST', v)) { done(); reopen(m); }
    }));
    if (c.approve_jefe) m.footer.append(post('Aprobar y enviar a Gerencia', 'approve/jefe', 'ok'));
    if (c.sign_gerente) m.footer.append(post('Aprobar y firmar como Gerente de Control Interno', 'sign/gerente', 'ok'));
    if (c.sign_contralor) m.footer.append(post('Aprobar y firmar como Contralor', 'sign/contralor', 'ok'));
    m.footer.append(closeBtn(m));
  }

  // ================================================================== registro de la página
  const route = () => window.dispatchEvent(new Event('hashchange'));
  S.pages.push({
    id: 'audits',
    title: currentTitle,
    perms: ['audit:read', 'audit:read_final', 'audit:sign_gerente', 'audit:financial_read', 'audit:systems_read'],
    render: async (el, args) => {
      const domain = currentDomain();
      if (args[0]) {
        ctx = null;
        const d = await S.get(`${A}/${args[0]}`);
        if (!d) return;
        if (domain && d.audit.audit_domain !== domain) {
          el.replaceChildren(h('div', { class: 'warn' }, 'La auditoría no pertenece al dominio asignado a su rol.'));
          return;
        }
        const tab = args[1] || 'resumen';
        await renderAudit(el, args[0], tab);
        if (ctx) {
          ctx.sheetId = args[2] || null;
          if (tab === 'cedulas' && ctx.sheetId) {
            const body = el.querySelector('div:last-child');
            body.replaceChildren();
            await cedulas(body);
          }
        }
      } else {
        await renderList(el, domain, currentTitle());
      }
    }
  });
})();
