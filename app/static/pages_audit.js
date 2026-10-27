// SICAS — Auditorías: expedientes, fases, cédulas, observaciones, evidencias, trabajo sin conexión, informes, PAC y firmas.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, fmt } = S;
  const A = '/audits';
  const LINES = [['AUTO', 'Auto'], ['PATRIMONIAL', 'Patrimonial'], ['PERSONAL', 'Personal'], ['ERP_TI', 'ERP / TI'], ['GENERAL', 'General']];
  const KINDS = [['SUSCRIPCION', 'Suscripción'], ['RECLAMO', 'Reclamo / indemnización'], ['SISTEMAS', 'Auditoría de Sistemas'],
    ['CXP', 'Cuentas por pagar'], ['CXC', 'Cuentas por cobrar'], ['ADMIN', 'Gestión administrativa'],
    ['CARTELERA', 'Cartelera fiscal y firmas autorizadas'], ['ADS', 'Evaluación ADS'], ['LOPCYMAT', 'Cuestionario LOPCYMAT'],
    ['SERV_SUC', 'Administración y servicios en sucursales']];
  const GENERAL_KINDS = ['CXP', 'CXC', 'ADMIN', 'CARTELERA', 'ADS', 'LOPCYMAT', 'SERV_SUC'];
  // Cuestionarios por bloques (Excel «Atributos Auditorias»): Sí / Parcialmente / No / N/A.
  const Q_RES = [['', '—'], ['CUMPLE', 'Sí'], ['PARCIAL', 'Parcialmente'], ['NO_CUMPLE', 'No'], ['NO_APLICA', 'N/A'], ['EXCEPCION', 'Excepción']];
  const Q_NEGATIVE = ['NO_CUMPLE', 'PARCIAL'];
  const Q_RISK = { BAJO: ['Riesgo bajo', 'LOW'], MEDIO: ['Riesgo medio', 'MEDIUM'], ALTO: ['Riesgo alto', 'HIGH'] };
  const isQuestionnaire = (ws) => ws.criteria.length > 0 && ws.criteria.every((c) => c.block);
  const LINE = Object.fromEntries(LINES), KIND = Object.fromEntries(KINDS);
  const PHASES = ['PLANIFICACION', 'TRABAJO_CAMPO', 'INFORME'];
  // Auditoría de Sistemas: 1 Levantamiento, 2 Documentación, 3 Pruebas de campo, 4 Informe.
  const SYSTEM_PHASES = ['LEVANTAMIENTO', 'DOCUMENTACION', 'PRUEBAS_CAMPO', 'INFORME'];
  const isSystems = (a) => a?.audit_domain === 'SISTEMAS';
  const phasesFor = (a) => (isSystems(a) ? SYSTEM_PHASES : PHASES);
  // Fases en las que se responden los controles (Sistemas: 1 a 3; resto: Trabajo de campo e Informe).
  const itemsPhase = (a) => (isSystems(a) ? SYSTEM_PHASES.slice(0, 3) : PHASES.slice(1)).includes(a?.phase);
  const workPhase = (a) => (isSystems(a) ? true : a?.phase !== 'PLANIFICACION');
  const RES = [['', '—'], ['CUMPLE', 'Cumple'], ['PARCIAL', 'Parcial'], ['NO_CUMPLE', 'No cumple'], ['NO_APLICA', 'No aplica'], ['EXCEPCION', 'Excepción']];
  const L = (v) => (v == null || v === '' ? '—' : (S.label2 || ((x) => x))(S.label(v)));
  let codes = null;
  const catalogs = async () => (codes = codes || await S.get(A + '/codification'));
  const opts = (cat) => Object.entries(cat || {}).map(([k, v]) => [k, `${k} — ${v}`]);
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
    return d === 'SISTEMAS' ? 'Auditoría de Sistemas' : 'Auditorías';
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
    if (can('audit:read', 'audit:read_final', 'audit:report_approve', 'audit:report_approve_gerente')) bar.append(h('button', { class: 'secondary', onclick: delegations }, 'Suplencias'));
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

  // ---------------------------------------------------------------- Suplencias temporales del flujo del informe
  // Jefe de Auditoría y Gerencia los autoriza el Contralor; al Contralor, Gerencia. Máximo 90 días.
  const STAGES = [['JEFE', 'Jefe de Auditoría'], ['GERENCIA', 'Gerencia'], ['CONTRALOR', 'Contralor']];
  async function delegations() {
    const d = await S.get(A + '/delegations?all=1');
    if (!d) return;
    const today = new Date().toISOString().slice(0, 10);
    const state = (x) => (x.revoked_at ? h('span', { class: 'badge REJECTED' }, 'Revocada') : x.active ? h('span', { class: 'badge ACTIVE' }, 'Vigente')
      : x.ends_on < today ? h('span', { class: 'badge INACTIVE' }, 'Vencida') : h('span', { class: 'badge PENDING' }, 'Programada'));
    const body = h('div', null,
      h('p', { class: 'muted' }, 'Cuando el titular de una etapa del informe final (Jefe de Auditoría, Gerencia o Contralor) no está, otra persona actúa en su nombre por un plazo de hasta 90 días. ' +
        'El flujo no cambia: cada decisión queda registrada como tomada por el suplente en nombre del titular, y el suplente firma con su propio certificado.'),
      d.needs_certificate ? h('div', { class: d.my_certificate ? 'okbox' : 'warn' }, d.my_certificate
        ? `Su certificado de firma: ${d.my_certificate.subject} (vence ${S.date(d.my_certificate.not_after)}).`
        : 'Usted firma informes: registre su propio certificado (.p12/.pfx). Nadie firma con el certificado de otra persona.') : null,
      tbl(['Etapa', 'Titular', 'Suplente', 'Desde', 'Hasta', 'Motivo', 'Autorizó', 'Estado', ''], d.delegations.map((x) => [
        x.stage_label + (x.audit_domain ? ' · ' + (x.audit_domain === 'SISTEMAS' ? 'Sistemas' : 'Operativa') : ''), x.titular_name, x.delegate_name,
        S.date(x.starts_on), S.date(x.ends_on), x.reason, x.authorized_by_name, state(x),
        h('button', { class: 'sm danger', disabled: !x.can_revoke, onclick: () => revoke(x) }, 'Revocar')])));
    const m = dlg('Suplencias', body);
    const reload = () => { m.close(); delegations(); };
    const revoke = async (x) => {
      const v = await S.ask('Revocar suplencia', [{ name: 'reason', label: 'Motivo (p. ej. regreso del titular)', type: 'textarea', required: true }], 'Revocar',
        `${x.delegate_name} dejará de actuar como ${x.stage_label} en nombre de ${x.titular_name}.`);
      if (v && await S.send(`${A}/delegations/${x.id}/revoke`, 'POST', v)) { S.say('Suplencia revocada.', true); reload(); }
    };
    if (d.can_authorize.length) m.footer.append(h('button', { onclick: async () => { if (await newDelegation(d.can_authorize)) reload(); } }, 'Nueva suplencia'));
    if (d.needs_certificate) m.footer.append(h('button', { class: 'secondary', onclick: async () => { if (await uploadCertificate()) reload(); } }, 'Mi certificado de firma'));
    m.footer.append(closeBtn(m));
  }

  async function newDelegation(allowed) {
    const c = await S.get(A + '/delegations/candidates');
    if (!c) return false;
    const keys = { JEFE_FINANCIERA: ['JEFE', 'FINANCIERA', 'Jefe de Auditoría (Operativa)'], JEFE_SISTEMAS: ['JEFE', 'SISTEMAS', 'Jefe de Auditoría de Sistemas'],
      GERENCIA: ['GERENCIA', null, 'Gerencia'], CONTRALOR: ['CONTRALOR', null, 'Contralor'] };
    const options = Object.keys(c.candidates).filter((k) => keys[k] && allowed.includes(keys[k][0]));
    if (!options.length) { S.say('No hay etapas con titulares registrados que usted pueda cubrir.'); return false; }
    const stageSel = h('select', null, options.map((k) => h('option', { value: k }, keys[k][2])));
    const titSel = h('select'), delSel = h('select');
    const who = (u) => `${u.name} (${u.username}${u.roles.length ? ' · ' + u.roles.join(', ') : ''})`;
    const fill = () => {
      const cc = c.candidates[stageSel.value];
      titSel.replaceChildren(...cc.titulars.map((u) => h('option', { value: u.id }, who(u))));
      delSel.replaceChildren(...(cc.delegates.length ? cc.delegates.map((u) => h('option', { value: u.id }, who(u))) : [h('option', { value: '' }, 'Ninguna persona cumple la segregación de funciones para esta etapa')]));
    };
    stageSel.addEventListener('change', fill); fill();
    const today = new Date().toISOString().slice(0, 10);
    const from = h('input', { type: 'date', value: today, min: today }), to = h('input', { type: 'date', min: today });
    const reason = h('textarea', { placeholder: 'Vacaciones, reposo médico, viaje…' });
    return new Promise((resolve) => {
      const m = dlg('Nueva suplencia', h('div', null,
        h('p', { class: 'muted' }, 'Solo se ofrecen suplentes que no violan la segregación de funciones (por ejemplo, quien ejecuta auditorías no puede cubrir al Contralor). ' +
          'El suplente de un Jefe de Auditoría debe pertenecer al mismo dominio.'),
        h('label', null, 'Etapa', stageSel), h('label', null, 'Titular ausente', titSel), h('label', null, 'Suplente', delSel),
        h('div', { class: 'toolbar' }, h('label', null, 'Desde', from), h('label', null, 'Hasta (máximo 90 días)', to)),
        h('label', null, 'Motivo (mínimo 10 caracteres)', reason)));
      m.footer.append(h('button', { class: 'secondary', onclick: () => { m.close(); resolve(false); } }, 'Cancelar'),
        h('button', { onclick: async (e) => {
          const [stage, domain] = keys[stageSel.value];
          e.target.disabled = true;
          const r = await S.send(A + '/delegations', 'POST', { stage, audit_domain: domain, titular_id: titSel.value, delegate_id: delSel.value,
            starts_on: from.value, ends_on: to.value, reason: reason.value.trim() });
          e.target.disabled = false;
          if (r) { S.say(r.note, true); m.close(); resolve(true); }
        } }, 'Autorizar suplencia'));
    });
  }

  async function uploadCertificate() {
    const v = await S.ask('Mi certificado de firma', [
      { name: 'file', label: 'Certificado (.p12 / .pfx, máximo 200 KB)', type: 'file', required: true },
      { name: 'passphrase', label: 'Contraseña del certificado', type: 'password' }], 'Guardar',
      'Cada firmante usa su propio certificado. Se guarda cifrado en el servidor y solo se usa cuando usted firma un informe.');
    if (!v) return false;
    const form = new FormData(); form.append('file', v.file); form.append('passphrase', v.passphrase || '');
    const r = await S.upload(A + '/signing-certificate', form);
    if (!r.ok) { S.say(S.err(r)); return false; }
    S.say(`Certificado registrado: ${r.data.subject} (vence ${S.date(r.data.not_after)}).`, true);
    return true;
  }

  async function newFile() {
    const [u, cat] = await Promise.all([S.get(A + '/units'), catalogs()]);
    if (!u || !cat) return;
    const systems = currentDomain() === 'SISTEMAS';
    if (!u.units.length) { S.say('No hay unidades ni sucursales. ' + (can('audit:unit_manage') ? 'Créelas en «Unidades y sucursales».' : 'Pida al Contralor que las registre.')); return; }
    const v = await S.ask('Nuevo expediente', [{ name: 'unit_id', label: 'Unidad / sucursal a auditar', type: 'select', options: u.units.map((x) => [x.id, `${x.name} (${x.code})`]) },
      { name: 'title', label: 'Título del expediente', required: true }, { name: 'objective', label: 'Objetivo general', type: 'textarea' },
      { name: 'period_from', label: 'Período revisado: desde', type: 'date', required: true }, { name: 'period_to', label: 'Período revisado: hasta', type: 'date', required: true },
      { name: 'audit_type', label: 'Tipo de auditoría (codificación)', type: 'select', options: systems ? [['S', 'S — Sistema']] : opts(cat.audit_types), value: systems ? 'S' : 'A' },
      { name: 'company', label: 'Compañía', type: 'select', options: opts(cat.companies), value: 'SC' }], 'Crear expediente',
      'Código: TIPO-COMPAÑÍA-CORRELATIVO-AÑO (p. ej. S-SC-001-2026). El expediente se crea primero; luego se abre la auditoría dentro de él.');
    if (!v) return;
    const r = await S.send(A + '/files', 'POST', { ...v, unit_id: Number(v.unit_id) });
    if (r) { S.say('Expediente creado: ' + r.code, true); route(); }
  }

  async function newAudit() {
    const [f, who, cat] = await Promise.all([S.get(A + '/files'), S.get(A + '/auditors'), catalogs()]);
    if (!f || !who || !cat) return;
    const sel2 = (items, value) => h('select', null, opts(items).map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
    const planSel = sel2(cat.plan_types, 'P'), procSel = sel2(cat.processes, currentDomain() === 'SISTEMAS' ? 'S' : 'O'),
      freqSel = sel2(cat.frequencies, 'G'), repCoSel = sel2(cat.report_companies, 'SC');
    const open = f.files.filter((x) => x.status === 'OPEN');
    if (!open.length) { S.say('Primero cree el expediente.'); return; }
    const sel = h('select', null, open.map((x) => h('option', { value: x.id }, `${x.code} — ${x.unit_name} — ${x.title}`)));
    const mod = h('select', null, h('option', { value: 'REMOTA' }, 'Remota'), h('option', { value: 'PRESENCIAL' }, 'Presencial'));
    const loc = h('input', { placeholder: 'Lugar (obligatorio si es presencial)' });
    const lines = LINES.filter(([v]) => !['ERP_TI', 'GENERAL'].includes(v)).map(([v, l]) => ({ v, el: h('input', { type: 'checkbox', checked: true }), l }));
    const kindSel = h('select', null, Object.entries(cat.audit_kinds || {}).map(([k, v]) => h('option', { value: k }, v.label)));
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
        const unitKind = file?.unit_kind;
        [...kindSel.options].forEach((o) => { o.disabled = !(cat.audit_kinds[o.value]?.units || []).includes(unitKind); });
        if (kindSel.selectedOptions[0]?.disabled) kindSel.value = [...kindSel.options].find((o) => !o.disabled)?.value || '';
        const usesLines = (cat.audit_kinds[kindSel.value]?.kinds || []).some((k) => ['SUSCRIPCION', 'RECLAMO'].includes(k));
        lineBox.replaceChildren(h('label', null, 'Tipo de auditoría', kindSel),
          usesLines ? h('div', null, h('p', null, 'Líneas en el alcance:'), h('div', { class: 'row' }, lines.map((x) => h('label', null, x.el, ' ', x.l)))) : null);
        procSel.value = { OPERATIVA: 'O', ESPECIAL: 'E', ADMINISTRATIVA: 'A', FINANCIERA: 'F' }[kindSel.value] || procSel.value;
        if (kindSel.value === 'ESPECIAL') { planSel.value = 'E'; freqSel.value = 'E'; }
      }
      cn.value = file?.responsible_name || '';
      cr.value = file?.responsible_role || '';
      scopeHint.textContent = system ? 'El cuestionario ERP/TI se prepara automáticamente con los 81 controles oficiales. Puede llenarlo manualmente o cargar el Excel oficial.' : 'Seleccione las líneas que forman parte del alcance.';
    };
    sel.addEventListener('change', sync);
    kindSel.addEventListener('change', sync);
    sync();
    const ta = (ph) => h('textarea', { placeholder: ph });
    const obj = ta('Objetivos de la auditoría'), scope = ta('Alcance'), proc = ta('Procedimientos / metodología (opcional)');
    const ps = h('input', { type: 'date' }), pe = h('input', { type: 'date' });
    const members = who.auditors.map((a) => ({ a, el: h('input', { type: 'checkbox' }) }));
    const m = dlg('Nueva auditoría', h('div', null,
      h('label', null, 'Expediente', sel), h('label', null, 'Modalidad', mod), h('label', null, 'Lugar', loc),
      h('p', { class: 'muted' }, 'Codificación de los informes: SIGLAS-PROCESO-TIPO-COMPAÑÍA-CORRELATIVO-AÑO (p. ej. P-S-G-SC-001-2026). La auditoría toma el código del expediente con el sufijo -A1, -A2…'),
      h('div', { class: 'toolbar' }, h('label', null, 'Siglas', planSel), h('label', null, 'Proceso', procSel), h('label', null, 'Tipo', freqSel), h('label', null, 'Compañía del informe', repCoSel)),
      lineBox, scopeHint,
      h('label', null, 'Objetivos', obj), h('label', null, 'Alcance', scope), h('label', null, 'Procedimientos', proc),
      h('div', { class: 'toolbar' }, h('label', null, 'Inicio previsto', ps), h('label', null, 'Fin previsto', pe)),
      h('div', { class: 'toolbar' }, h('label', null, 'Responsable de la unidad', cn), h('label', null, 'Cargo', cr)),
      h('p', { class: 'muted' }, 'Otros auditores del equipo (usted forma parte automáticamente):'),
      h('div', { class: 'checklist' }, members.map((x) => h('label', null, x.el, x.a.name)))));
    m.footer.append(closeBtn(m, 'Cancelar'), h('button', { onclick: async () => {
      const file = open.find((x) => x.id === sel.value),
        system = file?.audit_domain === 'SISTEMAS' || can('audit:systems_read') || can('audit:systems_execute') || can('audit:systems_manage') || can('audit:systems_review');
      const body = { file_id: sel.value, modality: mod.value, location: loc.value,
        lines: system ? [] : lines.filter((x) => x.el.checked).map((x) => x.v), audit_kind: system ? undefined : kindSel.value,
        objectives: obj.value, scope: scope.value, procedures: proc.value, planned_start: ps.value, planned_end: pe.value,
        contact_name: cn.value, contact_role: cr.value, member_ids: members.filter((x) => x.el.checked).map((x) => x.a.id),
        plan_type: planSel.value, process: procSel.value, frequency: freqSel.value, report_company: repCoSel.value };
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
    m.footer.append(h('button', { class: 'secondary', onclick: regulatoryCatalog }, 'Normativa SUDEASEG'), closeBtn(m));
  }
  async function regulatoryCatalog() {
    const d = await S.get(A + '/regulatory-catalog');
    if (!d) return;
    const edit = can('audit:template_manage');
    const m = dlg('Catálogo normativo SUDEASEG', h('div', null,
      h('p', { class: 'muted' }, 'El motor de reglas toma de aquí el criterio, la causa, el efecto y la recomendación de cada hallazgo de las auditorías operativas, especiales, administrativas y financieras. Los instrumentos se citan sin número de artículo: agréguelos al editar el criterio.'),
      tbl(['Tema', 'Criterio normativo', 'Palabras clave', ''], d.topics.map((t) => [t.label, t.criteria, (t.keywords || []).join(', ') || '—',
        edit ? h('button', { class: 'sm', onclick: async () => {
          const v = await S.ask('Tema: ' + t.label, [
            { name: 'criteria', label: 'Criterio (normativa aplicable)', type: 'textarea', value: t.criteria, required: true },
            { name: 'cause', label: 'Causa', type: 'textarea', value: t.cause, required: true },
            { name: 'effect', label: 'Efecto / riesgo', type: 'textarea', value: t.effect, required: true },
            { name: 'recommendation', label: 'Recomendación', type: 'textarea', value: t.recommendation, required: true },
            { name: 'keywords', label: 'Palabras clave (separadas por coma)', value: (t.keywords || []).join(', ') }], 'Guardar',
            'Los cambios aplican a los hallazgos que se generen desde ahora; los ya creados no cambian.');
          if (!v) return;
          v.keywords = String(v.keywords || '').split(',').map((x) => x.trim()).filter(Boolean);
          if (await S.send(`${A}/regulatory-catalog/${t.topic}`, 'PUT', v)) { S.say('Tema actualizado.', true); m.close(); regulatoryCatalog(); }
        } }, 'Editar') : null]))));
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
    const tabs = [['resumen', 'Resumen'], ['cedulas', 'Cédulas'], ['observaciones', 'Observaciones'], ['evidencias', 'Evidencias'], ['sinconexion', 'Sin conexión'], ['informes', 'Informes y PAC'], ['bitacora', 'Bitácora']];
    el.replaceChildren(h('div', { class: 'row' }, h('a', { href: '#/audits' }, '← Auditorías')),
      h('h2', null, `${a.code} — ${a.unit_name}`),
      h('div', { class: 'row' }, h('span', { class: 'badge ' + a.status }, ({ IN_PROGRESS: 'En curso', CLOSED: 'Cerrada' })[a.status] || a.status),
        h('span', null, `${a.modality === 'PRESENCIAL' ? 'Presencial' : 'Remota'} · ${a.file_code} · ${S.date(a.period_from)} → ${S.date(a.period_to)} · `), S.ratingBadge(d.overall.rating),
        d.overall.final != null ? h('b', null, ' ' + S.score(d.overall.final) + '%') : null, d.locked ? h('span', { class: 'badge PENDING' }, 'Bloqueada: informe en revisión/aprobado') : null),
      h('div', { class: 'tabs' }, tabs.map(([id, t]) => h('button', { class: id === ctx.tab ? 'active' : '', onclick: () => { location.hash = `#/audits/${aid}/${id}`; } }, t))), body);
    ({ resumen, cedulas, observaciones, evidencias, sinconexion, informes, bitacora })[ctx.tab](body);
  }
  const reload = () => renderAudit(ctx.el, ctx.aid, ctx.tab);

  // ---------------------------------------------------------------- Resumen y fases
  function resumen(el) {
    const { d } = ctx, a = d.audit;
    const sheets = Array.isArray(d.sheets) ? d.sheets : [];
    const PH = phasesFor(a);
    const phasePos = PH.indexOf(a.phase);
    const idx = phasePos < 0 ? 0 : phasePos;
    const phaseLog = Array.isArray(d.phase_log) ? d.phase_log : [];
    const team = Array.isArray(d.team) ? d.team : [];
    const indicators = d.indicators || { overall: {}, worksheets: [] };

    const scoreText = (v) => v == null ? 'Pendiente' : `${S.score(v)}%`;
    const signed = (v) => v == null ? '—' : (v > 0 ? '+' : '') + S.score(v);
    const pct = (v) => Math.min(100, Math.max(0, Number(v) || 0));
    const progress = (value) => {
      const track = h('div', { class: 'audit-progress' });
      const fill = h('span', { class: 'audit-progress-fill' });
      fill.style.width = `${pct(value)}%`;
      track.append(fill);
      return track;
    };
    const section = (title, subtitle, ...children) => h('section', { class: 'panel audit-summary-panel' },
      h('div', { class: 'audit-section-head' }, h('h3', null, title), subtitle ? h('p', { class: 'muted' }, subtitle) : null), ...children);

    // ---- fases
    const stepper = h('div', { class: 'stepper audit-phase-stepper' },
      PH.map((p, i) => h('div', { class: 'step ' + (i < idx ? 'done' : i === idx ? 'cur' : '') }, `${i + 1}. ${S.label2(p)}`)));
    const phaseBtns = h('div', { class: 'row audit-phase-actions' });
    if (ctx.canWrite) {
      if (idx < PH.length - 1) phaseBtns.append(h('button', { onclick: () => movePhase(PH[idx + 1]) }, (isSystems(a) && idx < 3 ? 'Cerrar fase y avanzar a ' : 'Avanzar a ') + S.label2(PH[idx + 1])));
      if (idx > 0) phaseBtns.append(h('button', { class: 'secondary', onclick: () => movePhase(PH[idx - 1]) }, 'Volver a ' + S.label2(PH[idx - 1])));
    }

    // ---- resultado de la evaluación
    const totalItems = sheets.reduce((n, s) => n + Number(s.items || 0), 0);
    const scoredItems = sheets.reduce((n, s) => n + Number(s.scored || 0), 0);
    const completion = totalItems ? Math.min(100, Math.round(scoredItems / totalItems * 100)) : 0;
    const exceptions = Number(d.overall.exceptions ?? sheets.reduce((n, s) => n + Number(s.exceptions || 0), 0));
    const excellent = d.thresholds?.excelente ?? 90;
    const hero = h('section', { class: 'panel audit-hero' },
      h('div', { class: 'audit-hero-main' },
        h('span', { class: 'audit-hero-label' }, isSystems(a) && a.phase !== 'INFORME' ? 'Calificación de la fase en curso' : 'Calificación final'),
        h('div', { class: 'audit-hero-score' }, scoreText(d.overall.final)),
        S.ratingBadge(d.overall.rating),
        h('div', { class: 'audit-hero-note' }, `${totalItems} controles · ${scoredItems} calificados · ${completion}% completado`),
        progress(completion)),
      h('div', { class: 'audit-hero-side' },
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Automática'), h('strong', null, scoreText(d.overall.auto))),
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Ajuste manual'), h('strong', null, a.manual_score != null ? scoreText(a.manual_score) : 'No')),
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Observaciones'), h('strong', null, String(d.observations ?? 0))),
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Evidencias'), h('strong', null, String(d.evidence ?? 0))),
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Excepciones'), h('strong', null, String(exceptions))),
        h('div', { class: 'audit-hero-metric' }, h('span', null, 'Cédulas'), h('strong', null, String(sheets.length)))),
      h('div', { class: 'audit-hero-foot' },
        h('span', { class: 'muted' }, d.thresholds?.scale === 'TRES_NIVELES'
          ? `Escala: Excelente > ${d.thresholds.excelente}%; Aceptable > ${d.thresholds.aceptable}% y ≤ ${d.thresholds.excelente}%; No satisfactoria ≤ ${d.thresholds.aceptable}%`
          : `Escala: Excelente > ${excellent}; Satisfactorio 70–90; Aceptable 60–69; Necesita mejoras 50–59; No satisfactoria ≤ 49`),
        a.manual_reason ? h('span', { class: 'audit-manual-reason' }, h('b', null, 'Justificación del ajuste: '), a.manual_reason) : null,
        can('audit:rate') && ctx.canWrite && workPhase(a)
          ? h('button', { class: 'sm', onclick: () => manual('/audits/' + a.id + '/rating', 'Calificación global', a.manual_score) }, 'Ajustar calificación global') : null));

    // ---- Sistemas: nota de cada fase y acciones de la fase en curso
    let phasesPanel = null;
    if (isSystems(a)) {
      const ps = d.overall.phase_scores || [];
      const finalCard = h('div', { class: 'audit-phase-score final' },
        h('span', null, '4. Nota final (promedio)'),
        h('strong', null, a.phase === 'INFORME' ? scoreText(d.overall.final) : '—'),
        a.phase === 'INFORME' ? S.ratingBadge(d.overall.rating) : h('span', { class: 'muted' }, 'Se calcula en la fase Informe'));
      const actions = h('div', { class: 'row' });
      const sysSheet = sheets.find((x) => x.kind === 'SISTEMAS');
      if (ctx.canWrite && ['LEVANTAMIENTO', 'DOCUMENTACION', 'PRUEBAS_CAMPO'].includes(a.phase) && sysSheet) {
        actions.append(h('button', { class: 'sm', onclick: async () => {
          const r = await S.send(`${A}/worksheets/${sysSheet.id}/auto-observations`, 'POST', {});
          if (r) { S.say(r.note, true); reload(); }
        } }, a.phase === 'LEVANTAMIENTO' ? 'Generar observaciones de las brechas' : 'Consolidar observaciones automáticas'));
      }
      if (['DOCUMENTACION', 'PRUEBAS_CAMPO', 'INFORME'].includes(a.phase)) {
        actions.append(h('button', { class: 'sm secondary', onclick: async () => {
          const v = await S.ask('Carta de solicitud de documentación', [{ name: 'due', label: 'Fecha límite de entrega', type: 'date' }], 'Generar carta',
            'Incluye los controles que la unidad declaró documentados en el levantamiento, estén actualizados o no.');
          if (v) S.openFile(`${A}/${a.id}/documentation-request.pdf${v.due ? '?due=' + encodeURIComponent(v.due) : ''}`, `${a.code}_solicitud_documentacion.pdf`, false);
        } }, 'Carta de solicitud de documentación'));
      }
      if (['PRUEBAS_CAMPO', 'INFORME'].includes(a.phase)) {
        actions.append(h('button', { class: 'sm secondary', onclick: () => S.openFile(`${A}/${a.id}/field-tests.pdf`, `${a.code}_programa_pruebas_campo.pdf`, false) },
          'Programa de pruebas de campo'));
      }
      const hint = {
        LEVANTAMIENTO: 'Fase 1: responda o cargue la cédula. Las brechas generan observaciones con riesgo, criterio, causa, efecto y recomendación.',
        DOCUMENTACION: 'Fase 2: solicite la documentación y verifique el soporte documental y la evidencia. La existencia del control se mantiene.',
        PRUEBAS_CAMPO: 'Fase 3: pruebe en campo solo los controles documentados (SI). Los demás conservan el resultado de Documentación.',
        INFORME: 'Fase 4: la nota final es el promedio de las fases 1, 2 y 3. Genere el informe final.'
      }[a.phase];
      phasesPanel = section('Notas por fase', hint,
        h('div', { class: 'audit-phase-scores' },
          ps.map((p, i) => h('div', { class: 'audit-phase-score' + (p.phase === a.phase ? ' current' : '') },
            h('span', null, `${i + 1}. ${S.label2(p.phase)}`),
            h('strong', null, p.score == null ? '—' : scoreText(p.score)),
            p.closed ? h('span', { class: 'muted' }, 'Cerrada ' + fmt(p.closed_at)) : p.score != null ? h('span', { class: 'muted' }, 'En curso') : h('span', { class: 'muted' }, 'Pendiente'))),
          finalCard),
        actions.childNodes.length ? actions : null);
    }

    // ---- auditorías no de Sistemas: hallazgos con normativa SUDEASEG
    if (!isSystems(a) && ctx.canWrite && ['TRABAJO_CAMPO', 'INFORME'].includes(a.phase)) {
      phasesPanel = section('Hallazgos de la evaluación', 'Los criterios incumplidos de la muestra se agrupan por tema y se redactan con la normativa SUDEASEG (catálogo editable por Contraloría).',
        h('div', { class: 'row' }, h('button', { class: 'sm', onclick: async () => {
          const r = await S.send(`${A}/${a.id}/auto-observations`, 'POST', {});
          if (r) { S.say(r.note, true); reload(); }
        } }, 'Generar hallazgos de los incumplimientos')));
    }

    // ---- indicadores por cédula (los mismos del cuestionario y del informe)
    const indicatorCards = (indicators.worksheets || []).map((w) => h('div', { class: 'audit-indicator-block' },
      h('div', { class: 'audit-indicator-head' },
        h('a', { href: `#/audits/${a.id}/cedulas/${w.id}` }, h('b', null, w.title || 'Cédula')),
        h('span', null, S.ratingBadge(w.rating), ' ', h('b', null, scoreText(w.score)))),
      h('div', { class: 'audit-indicator-grid' }, (w.indicators || []).map((i) =>
        h('div', { class: `audit-indicator ind-${i.key}` }, h('div', { class: 'n' }, String(i.value)), h('div', { class: 'l' }, i.label))))));
    const indicatorsPanel = section('Indicadores de la evaluación', 'Resultado del cuestionario por cédula. Seleccione una cédula para abrir sus controles.',
      indicatorCards.length ? h('div', null, indicatorCards) : h('p', { class: 'muted' }, 'No hay cédulas registradas.'));

    // ---- datos y equipo
    const dataPanel = section('Datos de la auditoría', null,
      h('div', { class: 'kv audit-summary-kv' },
        h('b', null, 'Expediente'), `${a.file_code} — ${a.title || ''}`,
        h('b', null, 'Tipo de auditoría'), isSystems(a) ? 'Auditoría de Sistemas' : (d.audit_kinds?.[a.audit_kind]?.label || a.audit_kind || '—'),
        h('b', null, 'Codificación de informes'), `${a.plan_type}-${a.process}-${a.frequency}-${a.report_company}-NNN-AAAA`,
        h('b', null, 'Unidad'), a.unit_name || '—',
        h('b', null, 'Objetivos'), a.objectives || '—',
        h('b', null, 'Alcance'), a.scope || '—',
        h('b', null, 'Procedimientos'), a.procedures || '—',
        h('b', null, 'Líneas'), (a.lines || []).map((l) => LINE[l] || l).join(', ') || '—',
        h('b', null, 'Modalidad'), a.modality === 'PRESENCIAL' ? 'Presencial' : a.modality === 'REMOTA' ? 'Remota' : (a.modality || '—'),
        h('b', null, 'Lugar'), a.location || '—',
        h('b', null, 'Colaborador en la unidad'), (a.contact_name || '—') + (a.contact_role ? ' · ' + a.contact_role : ''),
        h('b', null, 'Período revisado'), `${S.date(a.period_from) || '—'} → ${S.date(a.period_to) || '—'}`,
        h('b', null, 'Fechas previstas'), `${S.date(a.planned_start) || '—'} → ${S.date(a.planned_end) || '—'}`),
      d.can_edit_data ? h('div', { class: 'row' }, h('button', { class: 'sm', onclick: editAudit }, 'Editar datos de la auditoría')) : null);
    const teamPanel = section('Equipo auditor', null,
      team.length ? h('div', { class: 'audit-team-list' }, team.map((t) => h('div', { class: 'audit-team-member' },
        h('div', { class: 'audit-team-initials' }, t.initials || '—'),
        h('div', { class: 'audit-team-info' },
          h('b', null, t.name),
          h('span', null, h('span', { class: 'muted' }, 'Rol: '), t.system_role || 'Auditor')))))
        : h('p', { class: 'muted' }, 'Sin integrantes registrados.'));

    // ---- evolución por fase
    const phaseSnapshots = Array.isArray(d.phase_snapshots) ? d.phase_snapshots : [];
    const triggerNames = { PHASE_CHANGE: 'Cierre de fase', FINAL_REPORT_SUBMITTED: 'Envío del informe final', PAC_SENT: 'Envío del PAC' };
    const changedItems = phaseSnapshots.flatMap((snapshot) => (snapshot.variation?.items || []).map((it) => [
      fmt(snapshot.captured_at), S.label2(snapshot.phase), it.sheet || '—', it.ref, scoreText(it.before), scoreText(it.after),
      signed(it.delta), it.manual_reason || it.info_exception || it.observation || '—']));
    const sheetRows = phaseSnapshots.flatMap((snapshot) => (snapshot.scorecard?.worksheets || []).map((sheet) => [
      fmt(snapshot.captured_at), S.label2(snapshot.phase), sheet.title || 'Cédula', scoreText(sheet.final),
      `${Number(sheet.scored || 0)} / ${Number(sheet.items || 0)}`, String(Number(sheet.exceptions || 0))]));
    const evolution = section('Evolución de la calificación por fase',
      'Fotografía conservada al cerrar cada fase, enviar el informe final y enviar el PAC.',
      phaseSnapshots.length
        ? tbl(['Fecha', 'Fase', 'Evento', 'Nota final', 'Nivel', 'Variación', 'Motivo', 'Usuario'], phaseSnapshots.map((snapshot) => {
          const ov = snapshot.scorecard?.overall || {};
          return [fmt(snapshot.captured_at), S.label2(snapshot.phase), triggerNames[snapshot.trigger_action] || snapshot.trigger_action,
            scoreText(ov.final), S.ratingBadge(ov.rating || 'SIN_CALIFICAR'), signed(snapshot.variation?.overall_delta),
            snapshot.scorecard?.reason || '—', snapshot.captured_username || '—'];
        }))
        : h('p', { class: 'muted' }, 'Todavía no hay fotografías de fase. Se crean al cambiar de fase o enviar el informe.'),
      changedItems.length ? h('details', null, h('summary', null, `Ítems que originaron los ajustes (${changedItems.length})`),
        tbl(['Fecha', 'Fase', 'Cédula', 'Ref.', 'Antes', 'Después', 'Variación', 'Sustento'], changedItems)) : null,
      sheetRows.length ? h('details', null, h('summary', null, 'Detalle por cédula'),
        tbl(['Fecha', 'Fase', 'Cédula', 'Nota final', 'Ítems calificados', 'Excepciones'], sheetRows)) : null,
      h('details', null, h('summary', null, `Historial de fases (${phaseLog.length})`),
        tbl(['Fecha', 'De', 'A', 'Usuario', 'Nota'], phaseLog.map((p) => [
          fmt(p.changed_at), p.from_phase ? S.label2(p.from_phase) : '—', S.label2(p.to_phase), p.username || '—', p.note || '—']))));

    el.replaceChildren(h('div', { class: 'audit-phase-bar' }, stepper, phaseBtns),
      h('div', { class: 'audit-summary-dashboard' },
        hero,
        phasesPanel,
        indicatorsPanel,
        h('div', { class: 'audit-summary-layout' }, dataPanel, teamPanel),
        evolution));
  }

  async function editAudit() {
    const a = ctx.d.audit;
    const cat = await catalogs();
    if (!cat) return;
    const v = await S.ask('Editar datos de la auditoría', [
      { name: 'plan_type', label: 'Siglas del informe', type: 'select', options: opts(cat.plan_types), value: a.plan_type },
      { name: 'process', label: 'Proceso', type: 'select', options: opts(cat.processes), value: a.process },
      { name: 'frequency', label: 'Tipo (frecuencia)', type: 'select', options: opts(cat.frequencies), value: a.frequency },
      { name: 'report_company', label: 'Compañía del informe', type: 'select', options: opts(cat.report_companies), value: a.report_company },
      { name: 'objectives', label: 'Objetivos', type: 'textarea', value: a.objectives || '', required: true },
      { name: 'scope', label: 'Alcance', type: 'textarea', value: a.scope || '', required: true },
      { name: 'procedures', label: 'Procedimientos', type: 'textarea', value: a.procedures || '' },
      { name: 'modality', label: 'Modalidad', type: 'select', options: [['REMOTA', 'Remota'], ['PRESENCIAL', 'Presencial']], value: a.modality },
      { name: 'location', label: 'Lugar (obligatorio si es presencial)', value: a.location || '' },
      { name: 'contact_name', label: 'Colaborador en la unidad', value: a.contact_name || '' },
      { name: 'contact_role', label: 'Cargo del colaborador', value: a.contact_role || '' },
      { name: 'planned_start', label: 'Inicio previsto', type: 'date', value: S.date(a.planned_start) },
      { name: 'planned_end', label: 'Fin previsto', type: 'date', value: S.date(a.planned_end) },
      { name: 'reason', label: 'Motivo de la modificación (mínimo 10 caracteres; queda en la bitácora)', type: 'textarea', required: true }],
    'Guardar', 'Cada cambio queda registrado con el valor anterior, el nuevo, el usuario y el motivo.');
    if (!v) return;
    const r = await S.send(`${A}/${ctx.aid}`, 'PUT', v);
    if (r) { S.say(r.note || 'Datos actualizados.', true); reload(); }
  }

  async function movePhase(to) {
    const seq = phasesFor(ctx.d.audit);
    const back = seq.indexOf(to) < seq.indexOf(ctx.d.audit.phase);
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
      h('p', { class: 'muted' }, 'Los cuestionarios (Cartelera fiscal, Evaluación ADS, LOPCYMAT y Administración y servicios en sucursales) se responden una sola vez por unidad: una fila por pregunta.'),
      tbl(['Cédula', 'Criterios', 'Ítems', 'Excepciones', 'Final', 'Calificación'], d.sheets.map((s) => [s.title, s.criteria_count, s.items, s.exceptions, S.score(s.final), S.ratingBadge(s.rating)]), (i) => { location.hash = `#/audits/${ctx.aid}/cedulas/${d.sheets[i].id}`; }));
  }
  async function addSheet() {
    const system = ctx.d.audit.audit_domain === 'SISTEMAS';
    const allowed = ctx.d.audit_kinds?.[ctx.d.audit.audit_kind]?.kinds || [];
    const kinds = system ? [['SISTEMAS', 'Auditoría de Sistemas']] : KINDS.filter(([k]) => allowed.includes(k));
    const lines = system ? [['ERP_TI', 'ERP / TI']] : LINES.filter(([l]) => ctx.d.audit.lines.includes(l) && l !== 'ERP_TI');
    const v = await S.ask('Agregar cédula', [{ name: 'kind', label: 'Cédula', type: 'select', options: kinds },
      { name: 'line', label: 'Línea (Cuentas por pagar, por cobrar y Gestión administrativa usan General)', type: 'select', options: lines }], 'Crear');
    if (!v) return;
    if (!system) v.line = GENERAL_KINDS.includes(v.kind) ? 'GENERAL' : (v.line === 'GENERAL' ? (lines.find(([l]) => l !== 'GENERAL') || [''])[0] : v.line);
    if (await S.send(`${A}/${ctx.aid}/worksheets`, 'POST', v)) { S.say('Cédula creada.', true); reload(); }
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
          S.say(`Excel cargado. ${r.data.statistics.respondidas}/${r.data.statistics.total} controles respondidos.` +
            (r.data.observations_created ? ` Se redactaron ${r.data.observations_created} observaciones a partir de las brechas.` : ''), true);
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
      const rows = ws.items.map((it) => systemQuestionRow(it, criteria[it.ref], edit, paint, wid, d.phase_rules || {}));
      const qBody = h('tbody', null, rows);
      el.append(bar, h('div', { class: 'row' }, sum), stats, section,
        ...(!edit ? [h('div', { class: 'warn' }, d.audit.phase === 'PLANIFICACION' ? 'El cuestionario se califica en Trabajo de campo.' : d.audit.phase === 'INFORME' ? 'Fase de Informe: los controles quedaron cerrados en las fases 1 a 3.' : 'Solo lectura.')] : []),
        h('div', { class: 'grid-wrap audit-system-questionnaire' }, h('table', null, h('thead', null, h('tr', null, ['ID', 'Sección', 'Pregunta de auditoría', 'Existencia', 'Soporte documental', 'Evidencia / entregable', 'Puntaje', 'Observación', ''].map((x) => h('th', null, x)))), qBody)), S.paginate(qBody));
      return;
    }

    if (isQuestionnaire(ws)) return questionnaireView(el, d, ws, edit, bar, wid);

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

    const wBody = h('tbody', null, rows);
    worksheetContent.push(
      ws.items.length
        ? h('div', { class: 'grid-wrap audit-financial-worksheet' },
            h('table', null,
              h('thead', null,
                h('tr', null, head.map((x) => h('th', null, x)))),
              wBody
            )
          )
        : h('div', { class: 'empty panel' },
            'Sin ítems: agregue referencias o saque una muestra aleatoria.')
    );
    if (ws.items.length) worksheetContent.push(S.paginate(wBody));

    el.append(...worksheetContent);
  }

  // Cuestionario por bloques: índice ponderado, riesgo y bloques que no cumplen el promedio requerido.
  function questionnaireView(el, d, ws, edit, bar, wid) {
    const st = h('div'), sum = h('div', { class: 'row' });
    const paintStats = (s, q) => {
      const risk = Q_RISK[q?.risk];
      sum.replaceChildren(h('b', null, `${q?.index_label || 'Índice'}: ${S.score(q?.index)}%`), s.manual_override ? ` · Final ${S.score(s.final)}% (manual)` : '', ' ',
        risk ? h('span', { class: 'q-risk q-risk-' + q.risk }, risk[0]) : '', ` · ${q?.answered ?? 0}/${q?.total ?? 0} respondidas`);
      const weighted = q?.weighted && (q?.blocks || []).length > 1;
      st.replaceChildren(tbl(['Bloque', ...(weighted ? ['Peso'] : []), 'Preguntas', 'Cumplimiento', ...(weighted ? ['Aporte'] : []), 'Estado'],
        (q?.blocks || []).map((b) => [b.title, ...(weighted ? [S.score(b.weight * 100) + '%'] : []), `${b.answered + b.not_applicable + b.exceptions}/${b.questions}`,
          b.compliance == null ? '—' : S.score(b.compliance) + '%', ...(weighted ? [b.contribution == null ? '—' : S.score(b.contribution) + '%'] : []),
          b.critical ? h('span', { class: 'q-risk q-risk-ALTO' }, 'No cumple el promedio requerido') : b.complete ? h('span', { class: 'q-risk q-risk-BAJO' }, 'Cumple') : 'Pendiente'])),
        ...(q?.critical?.length ? [h('div', { class: 'warn' }, 'Bloques críticos: ' + q.critical.join('; ') + '. Cada respuesta negativa lleva su reseña y pasa al informe.')] : []));
    };
    paintStats(d.summary, d.statistics);
    const refresh = async () => { const f = await S.get(`${A}/worksheets/${wid}`); if (f) paintStats(f.summary, f.statistics); };
    if (edit && can('audit:rate')) {
      bar.append(h('button', { class: 'secondary', onclick: () => manual(`${A}/worksheets/${wid}/rating`, ws.title, ws.manual_score) }, 'Ajustar nota de la cédula'));
      if (ws.manual_score != null) bar.append(h('button', { class: 'secondary', onclick: () => clearManual(`${A}/worksheets/${wid}/rating`) }, 'Quitar ajuste'));
    }
    const items = Object.fromEntries(ws.items.map((it) => [it.ref, it]));
    const body = h('tbody');
    let block = null;
    ws.criteria.forEach((c) => {
      if (c.block !== block) {
        block = c.block;
        body.append(h('tr', { class: 'audit-q-block' }, h('td', { colspan: 5 }, h('b', null, c.block_title || c.section),
          c.block_weight != null && ws.criteria.some((x) => x.block !== c.block) ? ` · peso ${S.score(c.block_weight * 100)}%` : '')));
      }
      const it = items[c.code];
      if (it) body.append(questionRow(it, c, edit, refresh));
    });
    el.append(bar, sum, h('p', { class: 'muted' }, 'Sí = 1, Parcialmente = 0,5, No = 0; N/A no cuenta. Cumplimiento del bloque = promedio de sus respuestas (un bloque sin respuestas vale 0). Índice = suma de (peso del bloque × cumplimiento). Riesgo bajo ≥ 80 %, medio ≥ 60 %, alto < 60 %. Un bloque no cumple el promedio requerido si sus puntos suman menos de la mitad de sus preguntas (las N/A cuentan como preguntas).'),
      st, ...(ws.manual_reason ? [h('div', { class: 'warn' }, 'Ajuste manual de la cédula: ' + ws.manual_reason)] : []),
      ...(!edit ? [h('div', { class: 'warn' }, d.audit.phase === 'PLANIFICACION' ? 'El cuestionario se responde en Trabajo de campo.' : 'Solo lectura.')] : []),
      h('div', { class: 'grid-wrap audit-questionnaire' }, h('table', null,
        h('thead', null, h('tr', null, ['N°', 'Pregunta', 'Respuesta', 'Reseña (obligatoria si es No o Parcialmente)', ''].map((x) => h('th', null, x)))), body)));
  }

  function questionRow(it, c, edit, refresh) {
    const code = c.code;
    const state = { results: { ...(it.results || {}) }, observation: it.observation || '', info_exception: it.info_exception || '' };
    const saving = h('span', { class: 'saving' });
    const sel = h('select', { disabled: !edit }, Q_RES.map(([v, l]) => h('option', { value: v, selected: v === (state.results[code] || '') }, l)));
    const td = h('td', { class: 'res-' + (state.results[code] || '') }, sel);
    const obs = h('textarea', { disabled: !edit, value: state.observation, placeholder: 'Motivo de la respuesta negativa, evidencia o plan de acción' });
    const exc = h('textarea', { disabled: !edit, value: state.info_exception, placeholder: 'Qué información no se recibió', class: state.results[code] === 'EXCEPCION' ? '' : 'hidden' });
    let timer;
    const save = () => {
      const answer = state.results[code];
      if (Q_NEGATIVE.includes(answer) && !state.observation.trim()) { saving.textContent = 'falta la reseña'; obs.focus(); return; }
      if (answer === 'EXCEPCION' && !state.info_exception.trim()) { saving.textContent = 'describa la excepción'; exc.focus(); return; }
      clearTimeout(timer); saving.textContent = 'guardando…';
      timer = setTimeout(async () => {
        const r = await S.call(`${A}/items/${it.id}`, { method: 'PUT', json: state });
        if (!r.ok) { saving.textContent = ''; S.say(S.err(r)); return; }
        saving.textContent = 'guardado'; refresh();
      }, 350);
    };
    sel.addEventListener('change', () => {
      if (sel.value) state.results[code] = sel.value; else delete state.results[code];
      td.className = 'res-' + sel.value; exc.classList.toggle('hidden', sel.value !== 'EXCEPCION'); save();
    });
    obs.addEventListener('change', () => { state.observation = obs.value; save(); });
    exc.addEventListener('change', () => { state.info_exception = exc.value; save(); });
    const actions = h('td', null, saving);
    if (edit) actions.append(h('button', { class: 'sm', title: 'Crear una observación desde esta pregunta', onclick: () => obsForm({ item_id: it.id, title: '', condition: it.observation || '' }) }, '+ Obs.'));
    return h('tr', null, h('td', null, h('b', null, c.number || code)), h('td', null, c.text), td, h('td', null, obs, exc), actions);
  }

  function systemQuestionRow(it, criterion, edit, paint, wid, rules = {}) {
    const code = it.ref, cur = (it.results && it.results[code]) || {};
    const closedDoc = it.phase_results?.DOCUMENTACION?.results?.[code]?.documental;
    const notTestable = rules.only_documented && closedDoc && closedDoc !== 'SI';
    const lockControl = rules.lock_control;
    edit = edit && !notTestable;
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
      const sel = h('select', { disabled: !edit || (key === 'control' && lockControl) }, [['', '—'], ...options].map(([v, l]) => h('option', { value: v, selected: v === state.results[code][key] }, l)));
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
    return h('tr', { class: notTestable ? 'audit-row-muted' : '' }, h('td', null, h('b', null, code), notTestable ? h('div', { class: 'muted' }, 'No documentado: conserva Documentación') : null),
      h('td', null, criterion?.section || '—'), h('td', { title: criterion?.text || '' }, criterion?.text || 'Pregunta no disponible'),
      h('td', null, select('control', [['SI', 'Sí'], ['NO', 'No']])),
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
    const phaseOk = workPhase(ctx.d.audit);
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
      { name: 'cause', label: 'Causa', type: 'textarea', value: o.cause || '' }, { name: 'effect', label: 'Efecto / riesgo', type: 'textarea', value: o.effect || '' }, { name: 'recommendation', label: 'Recomendación', type: 'textarea', value: o.recommendation || '' },
      ...(o.id ? [{ name: 'reason', label: 'Motivo de la modificación (mínimo 10 caracteres; queda en el historial)', type: 'textarea', required: true }] : [])], 'Guardar',
      o.id ? 'La versión anterior se conserva: el informe final distingue el registro original de las modificaciones.' : undefined);
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
      ctx.canWrite && itemsPhase(ctx.d.audit) ? h('div', { class: 'toolbar' }, h('button', { onclick: () => S.openFile(`${A}/${ctx.aid}/offline-template`, `SICAS_${ctx.d.audit.code}_sin_conexion.xlsx`, false) }, 'Descargar paquete de trabajo (.xlsx)'))
        : h('div', { class: 'warn' }, 'Disponible para el equipo auditor desde Trabajo de campo, con cédulas creadas.'),
      h('p', { class: 'muted' }, 'El archivo está firmado por el servidor: si se altera su estructura o los identificadores, se rechaza. Las evidencias (fotos y documentos) se adjuntan en la pestaña Evidencias al conectarse.')));
    if (ctx.canWrite && itemsPhase(ctx.d.audit)) el.append(h('div', { class: 'panel' }, h('h3', null, 'Cargar el paquete trabajado'), h('div', { class: 'toolbar' }, h('label', null, 'Archivo .xlsx', file),
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
      if (workPhase(a)) bar.append(h('button', { onclick: gen('PREVIO') }, 'Generar informe previo (hacia la unidad)'));
      if (a.phase === 'INFORME') bar.append(h('button', { onclick: gen('FINAL') }, 'Generar informe final'));
    }
    el.append(bar, a.phase !== 'INFORME' ? h('div', { class: 'warn' }, 'El informe final se genera en la fase Informe. El informe previo puede generarse desde Trabajo de campo.') : null,
      tbl(['Código', 'Tipo', 'Versión', 'Estado', 'Generó', 'Creado', 'Enviado / aprobado'], d.reports.map((r) => [r.code || '—', r.kind === 'PREVIO' ? 'Previo' : 'Final', 'v' + r.version, S.badge(r.status), r.created_by_name, fmt(r.created_at),
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

  // ---------------------------------------------------------------- Bitácora del expediente
  const ACTION = {
    SUBMIT: 'Envío a revisión', RETURN: 'Devolución', APPROVE_JEFE: 'Aprobación del Jefe de Auditoría', SEND_PREVIO: 'Envío del informe previo',
    APPROVE_SIGN_GERENTE: 'Aprobación y firma de Gerencia', APPROVE_SIGN_CONTRALOR: 'Aprobación y firma de Contraloría'
  };
  const fmtChange = (changes) => {
    if (!changes || typeof changes !== 'object') return '—';
    const parts = Object.entries(changes).map(([k, v]) => v && typeof v === 'object' && 'before' in v && 'after' in v
      ? `${k}: ${JSON.stringify(v.before)} → ${JSON.stringify(v.after)}` : `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
    const text = parts.join(' · ');
    return text.length > 400 ? text.slice(0, 400) + '…' : (text || '—');
  };
  async function bitacora(el) {
    const d = await S.get(`${A}/${ctx.aid}/history`);
    if (!d) return;
    el.append(h('div', { class: 'panel' }, h('h3', null, 'Bitácora del expediente'),
      h('p', { class: 'muted' }, 'Registro inmutable de cambios de datos y decisiones del flujo. Los eventos no se pueden editar ni borrar desde la aplicación.'),
      d.events.length ? tbl(['Fecha', 'Tipo', 'Acción', 'Elemento', 'Cambio', 'Motivo / comentario', 'Fase / estado', 'Usuario'],
        d.events.map((ev) => ev.source === 'TRANSITION'
          ? [fmt(ev.created_at), 'Flujo', ACTION[ev.action] || ev.action, `Informe ${ev.kind === 'PREVIO' ? 'previo' : 'final'} v${ev.report_version}`,
            `${L(ev.from_status)} → ${L(ev.to_status)}`, ev.comment || '—', L(ev.to_status), ev.on_behalf_of ? `${ev.actor_username || '—'} (suplente, en nombre de ${ev.on_behalf_of})` : (ev.actor_username || '—')]
          : [fmt(ev.created_at), 'Dato', L(ev.action), `${L(ev.entity_type)}${ev.entity_id ? ' · ' + String(ev.entity_id).slice(0, 8) : ''}`,
            fmtChange(ev.changes), ev.reason || '—', [L(ev.audit_phase), ev.report_status ? ' / ' + L(ev.report_status) : ''].join(''),
            ev.actor_username || '—']))
        : h('p', { class: 'muted' }, 'Todavía no hay eventos registrados en la bitácora.')));
    const revs = (d.observation_revisions || []).filter((x) => x.revision > 1);
    if (revs.length) el.append(h('div', { class: 'panel' }, h('h3', null, 'Modificaciones de observaciones'),
      tbl(['Observación', 'Revisión', 'Fecha', 'Usuario', 'Campos', 'Motivo'], revs.map((x) => [x.data?.title || x.observation_id.slice(0, 8), String(x.revision),
        fmt(x.created_at), x.username || '—', (x.changed_fields || []).join(', '), x.reason || '—']))));
  }

  function reviewPointsBlock(d, rid, refresh) {
    const points = d.review_points || [];
    if (!points.length) return null;
    const pending = points.filter((p) => p.status === 'PENDIENTE').length;
    return h('div', null, h('h3', null, `Puntos de la devolución (${pending} pendiente${pending === 1 ? '' : 's'})`),
      tbl(['Elemento', 'Punto a corregir', 'Estado', 'Atención', ''], points.map((p) => [p.target_label || 'General', p.description, S.badge(p.status),
        p.status === 'ATENDIDO' ? `${p.attended_note} (${p.attended_by_name || '—'}, ${fmt(p.attended_at)})` : '—',
        p.status === 'PENDIENTE' && d.can.attend_points ? h('button', { class: 'sm', onclick: async () => {
          const v = await S.ask('Marcar punto como atendido', [{ name: 'note', label: 'Cómo se atendió (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Marcar atendido', p.description);
          if (v && await S.send(`${A}/review-points/${p.id}/attend`, 'POST', v)) { S.say('Punto atendido.', true); refresh(); }
        } }, 'Marcar atendido') : null])));
  }

  // ---------------------------------------------------------------- Informe: vista, firmas y revisión
  async function openReport(rid, after) {
    const d = await S.get(`${A}/reports/${rid}`);
    if (!d) return;
    const r = d.report, b = r.body, c = d.can;
    const done = () => { if (after) after(); };
    const reopen = (m) => { m.close(); openReport(rid, after); };
    const holder = {};
    const content = h('div', null,
      h('div', { class: 'kv' }, h('b', null, 'Código'), r.code || '—', h('b', null, 'Tipo'), r.kind === 'PREVIO' ? 'Informe previo (hacia la unidad)' : 'Informe final', h('b', null, 'Versión'), 'v' + r.version, h('b', null, 'Estado'), S.badge(r.status),
        h('b', null, 'Calificación'), [S.ratingBadge(b.overall.rating), ' ', b.overall.final != null ? S.score(b.overall.final) + '%' : ''], h('b', null, 'Observaciones'), String((b.observations || []).length),
        h('b', null, 'Limitaciones al alcance'), String((b.limitations || []).length), h('b', null, 'Ajustes manuales'), String((b.adjustments || []).length), r.sent_to ? [h('b', null, 'Enviado a'), r.sent_to] : null),
      r.status === 'RETURNED' ? h('div', { class: 'warn' }, 'Informe devuelto: atienda los puntos indicados, regenere y vuelva a enviar.') : null,
      d.acting_for ? h('div', { class: 'warn' }, `Usted actúa como suplente de ${d.acting_for.titular} (${d.acting_for.stage}) hasta el ${S.date(d.acting_for.ends_on)}: sus decisiones quedan registradas en su nombre.` +
        (d.acting_for.needs_certificate ? ' Para firmar debe subir su certificado en «Suplencias › Mi certificado de firma».' : '')) : null,
      d.reopening ? h('div', { class: 'warn' }, `Reapertura autorizada el ${fmt(d.reopening.authorized_at)} por ${d.reopening.username || '—'}: ${d.reopening.reason}`) : null,
      reviewPointsBlock(d, rid, () => { done(); reopen(holder.m); }),
      (d.transitions || []).length ? h('details', null, h('summary', null, `Historial de decisiones (${d.transitions.length})`),
        tbl(['Fecha', 'Decisión', 'De', 'A', 'Usuario', 'Comentario'], d.transitions.map((t) => [fmt(t.created_at), ACTION[t.action] || t.action,
          L(t.from_status), L(t.to_status), t.on_behalf_of ? `${t.actor_username || '—'} (suplente, en nombre de ${t.on_behalf_of})` : (t.actor_username || '—'), t.comment || '—']))) : null,
      (d.body_revisions || []).length > 1 ? h('details', null, h('summary', null, `Revisiones del contenido (${d.body_revisions.length})`),
        tbl(['Rev.', 'Fecha', 'Usuario', 'Motivo', 'SHA-256'], d.body_revisions.map((x) => [String(x.revision), fmt(x.created_at), x.username || '—', x.reason || '—', x.body_sha256.slice(0, 12) + '…']))) : null,
      r.kind === 'FINAL' ? h('div', null, h('h3', null, 'Firmas'), h('div', { class: 'kv' },
        h('b', null, 'Iniciales auditores'), d.team.map((t) => (d.signoffs.some((s) => s.signer_type === 'AUDITOR_INICIALES' && s.user_id === t.user_id && s.body_sha256 === r.body_sha256) ? '✔ ' : '✘ ') + t.initials + ' ').join('  '),
        h('b', null, 'Colaborador'), (d.signoffs.filter((s) => s.signer_type === 'COLABORADOR').slice(-1)[0]?.display) || (b.contact.name ? b.contact.name + ' (de la auditoría)' : 'sin registrar (firma manuscrita en la impresión)'),
        h('b', null, 'Contralor'), d.signatures.find((x) => x.signer_role === 'CONTRALOR') ? '✔ firmado ' + fmt(d.signatures.find((x) => x.signer_role === 'CONTRALOR').signed_at) : 'pendiente',
        h('b', null, 'Gerente de Control Interno'), d.signatures.find((x) => x.signer_role === 'GERENTE_CI') ? '✔ firmado ' + fmt(d.signatures.find((x) => x.signer_role === 'GERENTE_CI').signed_at) : 'pendiente')) : null,
      h('h3', null, 'Conclusión'), h('p', null, b.conclusion), b.conclusion_custom ? h('span', { class: 'muted' }, '(redactada por el auditor)') : h('span', { class: 'muted' }, '(generada automáticamente)'),
      r.kind === 'FINAL' ? h('div', null, h('h3', null, 'Revisión Auditor ↔ Contralor'), h('div', { class: 'thread' }, d.comments.length ? d.comments.map((x) => h('div', { class: 'c' }, h('b', null, `${x.full_name} (${x.kind.toLowerCase()}) `), h('span', { class: 'muted' }, fmt(x.created_at)), h('div', null, x.text))) : h('span', { class: 'muted' }, 'Sin comentarios'))) : null);
    const m = dlg(`${r.kind === 'PREVIO' ? 'Informe previo' : 'Informe final'} v${r.version}`, content);
    holder.m = m;
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
      const v = await S.ask('Devolver el informe al equipo auditor', [
        { name: 'comment', label: 'Motivo de la devolución (mínimo 10 caracteres)', type: 'textarea', required: true },
        { name: 'points', label: 'Puntos a corregir (uno por línea). Para una observación empiece con "Obs N:"', type: 'textarea' }], 'Devolver',
        'Cada punto queda pendiente hasta que el equipo lo marque como atendido; el informe no puede reenviarse con puntos pendientes.');
      if (!v) return;
      const obs = (await S.get(`${A}/${r.audit_id}/observations`))?.observations || [];
      const points = String(v.points || '').split('\n').map((l) => l.trim()).filter(Boolean).map((line) => {
        const mt = line.match(/^obs(?:ervaci[oó]n)?\s*(\d+)\s*[:.-]\s*(.+)$/i);
        const o = mt && obs.find((x) => String(x.seq) === mt[1]);
        return o ? { target_type: 'OBSERVATION', target_id: o.id, description: mt[2] } : { target_type: 'GENERAL', description: line };
      });
      if (await S.send(`${A}/reports/${rid}/return`, 'POST', { comment: v.comment, points })) { done(); reopen(m); }
    }));
    if (c.approve_jefe) m.footer.append(post('Aprobar y enviar a Gerencia', 'approve/jefe', 'ok'));
    if (c.sign_gerente) m.footer.append(post('Aprobar y firmar como Gerente de Control Interno', 'sign/gerente', 'ok'));
    if (c.sign_contralor) m.footer.append(post('Aprobar y firmar como Contralor', 'sign/contralor', 'ok'));
    if (c.reopen) m.footer.append(btn('Autorizar nueva versión', 'secondary', async () => {
      const v = await S.ask('Autorizar una nueva versión del informe firmado', [{ name: 'reason', label: 'Motivo (mínimo 20 caracteres)', type: 'textarea', required: true }], 'Autorizar',
        'La versión firmada no se modifica. El equipo auditor podrá generar la versión siguiente, que recorrerá de nuevo toda la cadena de revisión.');
      if (v) { const x = await S.send(`${A}/reports/${rid}/reopen`, 'POST', v); if (x) { S.say(x.note || 'Reapertura autorizada.', true); done(); reopen(m); } }
    }));
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
