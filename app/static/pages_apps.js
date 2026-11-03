// SICAS — Inventario de aplicativos (sistemas lógicos auditables) y Motor de reglas (retroalimentación, propuestas,
// reglas aprobadas por el Contralor y catálogo normativo único).
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl } = S;
  const A = '/audits';
  const pill = (text, cls) => h('span', { class: 'badge ' + (cls || 'PENDING') }, text);
  const opt = (obj) => Object.entries(obj || {});

  // ================================================================== inventario de aplicativos
  S.pages.push({
    id: 'applications', title: 'Inventario de aplicativos',
    perms: ['audit:systems_read', 'audit:systems_review', 'audit:unit_manage'],
    render: async (el) => {
      const [d, cat] = await Promise.all([S.get(A + '/applications'), S.get(A + '/app-catalog')]);
      if (!d || !cat) { el.replaceChildren(h('p', null, 'No se pudo cargar el inventario.')); return; }
      const draw = () => S.pages.find((p) => p.id === 'applications').render(el);
      const form = async (app) => {
        const p = (app && app.params) || cat.params;
        const fields = [
          ...(app ? [] : [{ name: 'code', label: 'Código (2-20 letras, números o guiones)', required: true, value: '' }]),
          { name: 'name', label: 'Nombre del aplicativo', required: true, value: app?.name || '' },
          { name: 'product', label: 'Producto', required: true, value: app?.product || '' },
          { name: 'vendor', label: 'Fabricante / proveedor', value: app?.vendor || '' },
          { name: 'version', label: 'Versión en producción', value: app?.version || '' },
          { name: 'category', label: 'Categoría', type: 'select', options: opt(cat.categories), value: app?.category || 'CORE' },
          { name: 'model', label: 'Modelo de servicio', type: 'select', options: opt(cat.models), value: app?.model || 'TERCERIZADO' },
          { name: 'criticality', label: 'Criticidad (BIA)', type: 'select', options: opt(cat.criticality), value: app?.criticality || 'ALTA' },
          { name: 'db_engine', label: 'Motor de base de datos', value: app?.db_engine || '' },
          { name: 'hosting', label: 'Alojamiento', value: app?.hosting || '' },
          { name: 'owner_unit_id', label: 'Unidad dueña del proceso', type: 'select', options: [['', '—'], ...d.units.map((u) => [String(u.id), u.name])], value: app?.owner_unit_id ? String(app.owner_unit_id) : '' },
          { name: 'custodian', label: 'Custodio técnico (TI)', value: app?.custodian || '' },
          { name: 'users_count', label: 'Usuarios activos', type: 'number', value: app?.users_count ?? '' },
          { name: 'modules', label: 'Módulos habilitados', type: 'textarea', value: app?.modules || '' },
          { name: 'interfaces', label: 'Interfaces con otros sistemas', type: 'textarea', value: app?.interfaces || '' },
          { name: 'template_code', label: 'Plantilla de auditoría', type: 'select', options: opt(cat.templates), value: app?.template_code || 'ACSELX' },
          ...Object.keys(cat.params).map((k) => ({ name: 'p_' + k, label: cat.param_labels[k], type: 'number', value: String(p[k] ?? cat.params[k]) }))];
        const v = await S.ask(app ? `Editar ${app.name}` : 'Nuevo aplicativo', fields, 'Guardar',
          'Los objetivos (RPO, RTO, frecuencia de pruebas) se usan para evaluar los datos que informan las áreas en las encuestas.');
        if (!v) return;
        const params = {};
        for (const k of Object.keys(cat.params)) { params[k] = Number(v['p_' + k]); delete v['p_' + k]; }
        const payload = { ...v, params, users_count: v.users_count === '' ? null : Number(v.users_count), owner_unit_id: v.owner_unit_id || null };
        const r = app ? await S.send(`${A}/applications/${app.unit_id}`, 'PUT', payload) : await S.send(A + '/applications', 'POST', payload);
        if (r) { S.say('Aplicativo guardado.', true); draw(); }
      };
      const rows = d.applications.map((a) => [h('strong', null, a.code), a.name, `${a.product}${a.version ? ' ' + a.version : ''}`, a.vendor || '—',
        cat.categories[a.category] || a.category, pill(cat.criticality[a.criticality] || a.criticality, a.criticality === 'ALTA' ? 'HIGH' : a.criticality === 'MEDIA' ? 'MEDIUM' : 'LOW'),
        a.owner_unit_name || '—', String(a.audits), a.active ? 'Activo' : 'Inactivo',
        cat.can_manage ? h('button', { class: 'sm secondary', onclick: () => form(a) }, 'Editar') : '']);
      el.replaceChildren(
        h('h2', null, 'Inventario de aplicativos'),
        h('p', { class: 'muted' }, 'Sistemas lógicos auditables (core, ERP, nómina, contabilidad…). La auditoría de un aplicativo se crea igual que cualquier '
          + 'auditoría de Sistemas: abra un expediente seleccionando el aplicativo; el cuestionario sale de su plantilla y se reparte en encuestas por área.'),
        cat.can_manage ? h('div', { class: 'toolbar' }, h('button', { onclick: () => form(null) }, 'Nuevo aplicativo')) : null,
        tbl(['Código', 'Nombre', 'Producto', 'Fabricante', 'Categoría', 'Criticidad', 'Dueño del proceso', 'Auditorías', 'Estado', ''], rows));
    }
  });

  // ================================================================== motor de reglas
  const KIND_LABEL = { WEIGHT: 'Peso del control', RISK: 'Riesgo por defecto', RECOMMEND: 'Recomendación por defecto', SUPPRESS: 'No redactar automáticamente' };
  const STATUS_CLASS = { PROPUESTA: 'PENDING', APROBADA: 'OK', RECHAZADA: 'HIGH', RETIRADA: 'PENDING' };
  const valueText = (p) => p.kind === 'WEIGHT' ? `Peso ${p.value.weight} (crítico)` : p.kind === 'RISK' ? `Riesgo ${p.value.risk}`
    : p.kind === 'RECOMMEND' ? p.value.recommendation : 'Suprimir la redacción automática';

  S.pages.push({
    id: 'engine', title: 'Motor de reglas',
    perms: ['rule:configure', 'audit:systems_review', 'audit:financial_review'],
    render: async (el) => {
      const tab = (location.hash.split('/')[2] || 'propuestas');
      const go = (t) => { location.hash = '#/engine/' + t; };
      const tabs = [['propuestas', 'Propuestas'], ['retroalimentacion', 'Retroalimentación'], ['reglas', 'Reglas aprobadas'], ['normativa', 'Normativa']];
      const body = h('div');
      el.replaceChildren(h('h2', null, 'Motor de reglas'),
        h('p', { class: 'muted' }, 'El motor aprende en todas las auditorías (Sistemas, aplicativos, Operativa, Financiera, Administrativa y Especial) de las decisiones del auditor y del historial de controles y hallazgos, pero nunca cambia sus reglas solo: '
          + 'plantea propuestas con su evidencia y el Contralor las aprueba o rechaza. Cada decisión queda registrada con su autor y fecha.'),
        h('div', { class: 'tabs' }, tabs.map(([id, t]) => h('button', { class: id === tab ? 'active' : '', onclick: () => go(id) }, t))), body);
      body.replaceChildren(S.loading());

      if (tab === 'retroalimentacion') {
        const d = await S.get(A + '/engine/feedback');
        if (!d) return;
        body.replaceChildren(
          h('div', { class: 'cards' }, S.stat(d.summary.total, 'Decisiones registradas'), ...d.summary.by_kind.map((k) => S.stat(k.count, k.label))),
          h('section', { class: 'panel' }, h('h3', null, 'Últimas decisiones del auditor'),
            tbl(['Fecha', 'Decisión', 'Tema / control', 'Auditoría', 'Usuario', 'Motivo'],
              d.events.map((e) => [S.date(e.created_at), d.kinds[e.kind] || e.kind, e.pattern_label || e.pattern_key || '—', e.audit_code || '—', e.user_name || '—', e.reason || '—']))));
        return;
      }
      if (tab === 'normativa') {
        const d = await S.get(A + '/norms');
        if (!d) return;
        const edit = async (n) => {
          const v = await S.ask(n.code, [
            { name: 'status', label: 'Estado', type: 'select', options: [['VIGENTE', 'Vigente'], ['POR_VALIDAR', 'Por validar'], ['DEROGADA', 'Derogada']], value: n.status },
            { name: 'summary', label: 'Resumen', type: 'textarea', value: n.summary || '' }], 'Guardar', `${n.reference} — ${n.title}`);
          if (v && await S.send(`${A}/norms/${encodeURIComponent(n.code)}`, 'PUT', v)) S.pages.find((p) => p.id === 'engine').render(el);
        };
        body.replaceChildren(h('section', { class: 'panel' }, h('h3', null, 'Catálogo normativo único'),
          h('p', { class: 'muted' }, 'Cada control de los aplicativos cita estas normas y el motor arma con ellas el criterio de cada hallazgo. «Por validar»: la referencia debe confirmarla el área legal.'),
          tbl(['Código', 'Fuente', 'Referencia', 'Título', 'Estado', ''],
            d.norms.map((n) => [h('strong', null, n.code), d.sources[n.source] || n.source, n.reference, h('div', null, h('div', null, n.title), h('div', { class: 'muted' }, n.summary || '')),
              pill(n.status === 'VIGENTE' ? 'Vigente' : n.status === 'POR_VALIDAR' ? 'Por validar' : 'Derogada', n.status === 'VIGENTE' ? 'OK' : n.status === 'POR_VALIDAR' ? 'MEDIUM' : 'HIGH'),
              d.can_edit ? h('button', { class: 'sm secondary', onclick: () => edit(n) }, 'Editar') : '']))));
        return;
      }
      // Propuestas y reglas: analizar patrones al abrir (no aplica nada: solo crea propuestas pendientes).
      await S.send(A + '/engine/analyze', 'POST', {});
      const d = await S.get(A + '/engine/proposals');
      if (!d) return;
      const redraw = () => S.pages.find((p) => p.id === 'engine').render(el);
      if (tab === 'reglas') {
        const retire = async (r) => {
          const v = await S.ask('Retirar regla', [{ name: 'note', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Retirar');
          if (v && await S.send(`${A}/engine/rules/${r.id}/retire`, 'POST', v)) redraw();
        };
        body.replaceChildren(h('section', { class: 'panel' }, h('h3', null, 'Reglas aprobadas'),
          tbl(['Tipo', 'Tema / control', 'Valor', 'Aprobada por', 'Fecha', 'Estado', ''],
            d.rules.map((r) => [KIND_LABEL[r.kind] || r.kind, r.target_label || r.target, valueText(r), r.approved_by_name || '—', S.date(r.approved_at),
              r.active ? pill('Vigente', 'OK') : pill('Retirada ' + S.date(r.retired_at), 'PENDING'),
              r.active && d.can_decide ? h('button', { class: 'sm secondary', onclick: () => retire(r) }, 'Retirar') : '']))));
        return;
      }
      const decide = async (p, decision) => {
        const v = await S.ask(decision === 'APROBADA' ? 'Aprobar propuesta' : 'Rechazar propuesta',
          [{ name: 'note', label: 'Fundamento de la decisión (mínimo 10 caracteres)', type: 'textarea', required: true }],
          decision === 'APROBADA' ? 'Aprobar' : 'Rechazar', p.rationale);
        if (v && await S.send(`${A}/engine/proposals/${p.id}/decide`, 'POST', { decision, note: v.note })) { S.say('Decisión registrada.', true); redraw(); }
      };
      const show = (p) => {
        const m = S.modal('Evidencia de la propuesta', h('div', null, h('p', null, p.rationale),
          tbl(['Auditoría', 'Fecha', 'Usuario', 'Antes', 'Después'],
            (p.evidence || []).map((e) => [e.audit_code || '—', e.at || '—', e.by || '—', e.before ? JSON.stringify(e.before) : '—', e.after ? JSON.stringify(e.after) : '—']))));
        m.footer.append(h('button', { class: 'secondary', onclick: () => m.close() }, 'Cerrar'));
      };
      const pending = d.proposals.filter((p) => p.status === 'PROPUESTA');
      body.replaceChildren(
        h('section', { class: 'panel' }, h('h3', null, `Propuestas pendientes (${pending.length})`),
          pending.length ? null : h('p', { class: 'muted' }, 'No hay patrones repetidos suficientes para proponer reglas nuevas. Se requieren al menos 3 decisiones coincidentes.'),
          tbl(['Tipo', 'Tema / control', 'Propuesta', 'Fundamento', ''],
            pending.map((p) => [KIND_LABEL[p.kind] || p.kind, p.target_label || p.target, valueText(p), p.rationale,
              h('div', { class: 'actions' }, h('button', { class: 'sm secondary', onclick: () => show(p) }, 'Evidencia'),
                d.can_decide ? h('button', { class: 'sm ok', onclick: () => decide(p, 'APROBADA') }, 'Aprobar') : null,
                d.can_decide ? h('button', { class: 'sm danger', onclick: () => decide(p, 'RECHAZADA') }, 'Rechazar') : null)]))),
        h('section', { class: 'panel' }, h('h3', null, 'Historial de propuestas'),
          tbl(['Tipo', 'Tema / control', 'Propuesta', 'Estado', 'Decidida por', 'Fecha', 'Fundamento'],
            d.proposals.filter((p) => p.status !== 'PROPUESTA').map((p) => [KIND_LABEL[p.kind] || p.kind, p.target_label || p.target, valueText(p),
              pill(p.status.charAt(0) + p.status.slice(1).toLowerCase(), STATUS_CLASS[p.status]), p.decided_by_name || '—', S.date(p.decided_at), p.decision_note || '—']))));
    }
  });
})();
