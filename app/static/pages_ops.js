// SICAS — Cargas, hallazgos, reglas, LC/FT e informes (dictámenes).
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, fmt } = S;
  const close = (m) => h('button', { class: 'secondary', onclick: () => m.close() }, 'Cerrar');

  // ------------------------------------------------------------------ Cargas
  const DS = [['policies', 'Pólizas'], ['claims', 'Siniestros'], ['reserves', 'Reservas'], ['payments', 'Pagos']];
  S.pages.push({ id: 'ingestion', title: 'Cargas', perms: ['ingestion:read'], render: async (el) => {
    el.append(h('h2', null, 'Carga de datos (CSV)'));
    const sel = h('select', null, DS.map(([v, l]) => h('option', { value: v }, l)));
    const file = h('input', { type: 'file', accept: '.csv,.txt' });
    const out = h('div');
    if (can('ingestion:upload')) {
      el.append(h('div', { class: 'panel' }, h('div', { class: 'toolbar' }, h('label', null, 'Tipo de datos', sel), h('label', null, 'Archivo CSV', file),
        h('button', { onclick: async (e) => S.busy(e.target, async () => {
          if (!file.files[0]) { S.say('Seleccione un archivo.'); return; }
          const fd = new FormData(); fd.append('dataset', sel.value); fd.append('file', file.files[0]);
          const r = await S.upload('/ingestion/uploads', fd);
          if (!r.ok) { S.say(S.err(r)); return; }
          S.say('Archivo recibido. Procesando…', true); file.value = ''; load();
        }) }, 'Cargar'),
        h('button', { class: 'secondary', onclick: () => S.openFile('/ingestion/templates/' + sel.value, `plantilla_${sel.value}.csv`, false) }, 'Descargar plantilla')),
        h('p', { class: 'muted' }, 'Todas las cargas exigen la columna currency (VES, USD o EUR). Fechas AAAA-MM-DD. Un archivo ya cargado se rechaza (misma huella).')));
    }
    el.append(out);
    let timer;
    const load = async () => {
      const d = await S.get('/ingestion/uploads');
      if (!d) return;
      out.replaceChildren(h('h3', null, 'Cargas recientes'), tbl(['Fecha', 'Tipo', 'Estado', 'Procesadas', 'Rechazadas', 'Conciliada', 'Usuario'], d.jobs.map((j) => [
        fmt(j.created_at), (DS.find((x) => x[0] === j.dataset) || [0, j.dataset])[1], S.badge(j.status), j.rows_processed, j.rows_rejected,
        j.reconciled == null ? '—' : (j.reconciled ? 'Sí' : h('b', null, 'NO')), j.uploaded_by]), can('ingestion:review_rejects') ? (i) => rejects(d.jobs[i]) : null),
        h('p', { class: 'muted' }, 'Haga clic en una fila para ver las filas rechazadas y el motivo.'));
      clearTimeout(timer);
      if (d.jobs.some((j) => ['QUEUED', 'PROCESSING'].includes(j.status)) && document.body.contains(el)) timer = setTimeout(load, 4000);
    };
    S.onLeave = () => clearTimeout(timer);
    const rejects = async (j) => {
      const d = await S.get(`/ingestion/uploads/${j.id}/rejects`);
      if (!d) return;
      const m = S.modal('Filas rechazadas', d.rejects.length ? tbl(['Línea', 'Motivo'], d.rejects.map((r) => [r.line, (r.errors || []).join('; ')])) : h('p', null, 'Sin filas rechazadas.'));
      m.footer.append(close(m));
    };
    load();
  } });

  // ------------------------------------------------------------------ Hallazgos
  S.pages.push({ id: 'findings', title: 'Hallazgos', perms: ['finding:read'], render: async (el) => {
    el.append(h('h2', null, 'Hallazgos del motor de reglas'));
    const st = h('select', null, ['OPEN', 'IN_REVIEW', 'ESCALATED', 'CLOSED_FP', 'CLOSED_RESOLVED'].map((x) => h('option', { value: x }, S.label(x))));
    const sv = h('select', null, h('option', { value: '' }, '(todas)'), ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((x) => h('option', { value: x }, S.label(x))));
    const out = h('div');
    const bar = h('div', { class: 'toolbar' }, h('label', null, 'Estado', st), h('label', null, 'Severidad', sv), h('button', { onclick: () => load() }, 'Buscar'));
    if (can('rule:execute')) bar.append(h('button', { class: 'secondary', onclick: async () => {
      if (!window.confirm('La ejecución global analizará todas las cargas disponibles de pólizas, siniestros, reservas y pagos. ¿Desea continuar?')) return;
      if (await S.send('/engine/runs', 'POST', { scope: 'GLOBAL' })) S.say('Motor global en ejecución. Actualice en unos segundos.', true);
    } }, 'Ejecutar motor global'));
    el.append(bar, out);
    const load = async () => {
      const d = await S.get(`/engine/findings?status=${st.value}` + (sv.value ? '&severity=' + sv.value : ''));
      if (!d) return;
      out.replaceChildren(tbl(['Severidad', 'Regla', 'Entidad', 'Puntaje', 'Descripción'], d.findings.map((f) => [S.badge(f.severity), f.rule_code, f.entity_type + ' ' + f.entity_id, Number(f.score).toFixed(0), f.message]), (i) => detail(d.findings[i].id)),
        h('p', { class: 'muted' }, 'Las alertas LC/FT están en el módulo LC/FT.'));
    };
    const detail = async (id) => {
      const d = await S.get('/engine/findings/' + id);
      if (!d) return;
      const f = d.finding;
      const m = S.modal(`Hallazgo #${f.id} — ${f.rule_code}`, h('div', null, h('p', null, f.message), h('div', { class: 'kv' }, h('b', null, 'Severidad'), S.badge(f.severity), h('b', null, 'Estado'), S.badge(f.status)), h('h3', null, 'Evidencia'), S.json(f.evidence),
        f.closed_reason ? h('p', null, h('b', null, 'Motivo de cierre: '), f.closed_reason) : null));
      const act = (label, cls, path, withReason, extra) => h('button', { class: cls, onclick: async () => {
        const v = withReason ? await S.ask(label, [{ name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }, ...(extra || [])], label) : {};
        if (!v) return;
        if (await S.send(`/engine/findings/${id}/${path}`, 'POST', { reason: v.reason, false_positive: v.false_positive })) { m.close(); S.say('Hecho.', true); load(); }
      } }, label);
      if (can('finding:triage')) m.footer.append(act('Marcar en revisión', 'secondary', 'review', false));
      if (can('finding:escalate')) m.footer.append(act('Escalar', 'secondary', 'escalate', true));
      if (can('finding:close')) m.footer.append(act('Cerrar', 'danger', 'close', true, [{ name: 'false_positive', label: 'Es un falso positivo', type: 'checkbox' }]));
      m.footer.append(close(m));
    };
    load();
  } });

  // ------------------------------------------------------------------ Reglas
  S.pages.push({ id: 'rules', title: 'Reglas', perms: ['rule:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Reglas de anomalías, fraude y LC/FT'));
      const d = await S.get('/engine/rules');
      if (!d) return;
      el.append(h('p', { class: 'muted' }, 'Los umbrales son valores iniciales. Calíbrelos con datos históricos; los de LC/FT los fija el Oficial de Cumplimiento. Cada cambio queda en el audit trail.'),
        tbl(['Regla', 'Descripción', 'Parámetros', 'Activa', ''], d.rules.map((r) => [r.code, r.title, h('code', null, JSON.stringify(r.params || r.defaults)), r.enabled ? 'Sí' : 'No',
          can('rule:configure') ? h('button', { class: 'sm', onclick: () => edit(r) }, 'Editar') : ''])));
    };
    const edit = async (r) => {
      const v = await S.ask('Editar ' + r.code, [{ name: 'params', label: 'Parámetros (JSON)', type: 'textarea', value: JSON.stringify(r.params || r.defaults, null, 2), required: true }, { name: 'enabled', label: 'Regla activa', type: 'checkbox', value: r.enabled }], 'Guardar');
      if (!v) return;
      let params; try { params = JSON.parse(v.params); } catch (_) { S.say('JSON inválido.'); return; }
      if (await S.send('/engine/rules/' + r.code, 'PUT', { params, enabled: v.enabled })) { S.say('Regla actualizada.', true); draw(); }
    };
    draw();
  } });

  // ------------------------------------------------------------------ LC/FT
  S.pages.push({ id: 'lcft', title: 'LC/FT', perms: ['lcft:alert_read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Prevención de LC/FT'));
      const st = h('select', null, ['OPEN', 'IN_REVIEW', 'ESCALATED', 'CLOSED_FP', 'CLOSED_RESOLVED'].map((x) => h('option', { value: x }, S.label(x))));
      const out = h('div');
      el.append(h('div', { class: 'toolbar' }, h('label', null, 'Estado', st), h('button', { onclick: () => load() }, 'Buscar')), out);
      const load = async () => {
        const d = await S.get('/compliance/alerts?status=' + st.value);
        if (!d) return;
        out.replaceChildren(tbl(['Severidad', 'Regla', 'Entidad', 'Descripción'], d.alerts.map((a) => [S.badge(a.severity), a.rule_code, a.entity_type + ' ' + a.entity_id, a.message]), can('lcft:alert_manage') ? (i) => manage(d.alerts[i]) : null));
      };
      const manage = async (a) => {
        const v = await S.ask('Gestionar alerta #' + a.id, [{ name: 'status', label: 'Nuevo estado', type: 'select', options: [['IN_REVIEW', 'En revisión'], ['ESCALATED', 'Escalar'], ['CLOSED_FP', 'Cerrar: falso positivo'], ['CLOSED_RESOLVED', 'Cerrar: resuelta']] },
          { name: 'reason', label: 'Decisión documentada (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Registrar', a.message);
        if (v && await S.send(`/compliance/alerts/${a.id}/status`, 'POST', v)) { S.say('Registrado.', true); load(); }
      };
      load();
      const w = await S.get('/compliance/watchlist');
      if (w) el.append(h('h3', null, 'Lista restrictiva'), can('lcft:rule_configure') ? h('div', { class: 'toolbar' }, h('button', { onclick: addWatch }, 'Agregar identificador')) : null,
        tbl(['Lista', 'Identificador (enmascarado)', 'Nombre', 'Agregado', 'Activo', ''], w.watchlist.map((x) => [x.list_name, x.doc_id_norm, x.full_name || '', fmt(x.added_at), x.active ? 'Sí' : 'No',
          can('lcft:rule_configure') && x.active ? h('button', { class: 'sm danger', onclick: async () => { if (confirm('¿Desactivar?') && await S.send(`/compliance/watchlist/${x.id}/deactivate`, 'POST')) draw(); } }, 'Desactivar') : ''])));
    };
    const addWatch = async () => {
      const v = await S.ask('Agregar a la lista restrictiva', [{ name: 'list_name', label: 'Nombre de la lista', required: true }, { name: 'doc_id', label: 'Cédula / RIF', required: true }, { name: 'full_name', label: 'Nombre (opcional)' }], 'Agregar');
      if (v && await S.send('/compliance/watchlist', 'POST', v)) { S.say('Agregado.', true); draw(); }
    };
    draw();
  } });

  // ------------------------------------------------------------------ Informes (dictámenes y providencias)
  S.pages.push({ id: 'reports', title: 'Dictámenes', perms: ['report:read', 'report:read_approved'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Dictámenes y providencias'));
      const bar = h('div', { class: 'toolbar' });
      if (can('report:draft')) bar.append(h('button', { onclick: create }, 'Nuevo informe'));
      if (can('report:verify_signature')) bar.append(h('button', { class: 'secondary', onclick: verify }, 'Verificar un PDF firmado'));
      const d = await S.get('/reports');
      if (!d) return;
      el.append(bar, tbl(['Folio', 'Tipo', 'Título', 'Estado', 'Redactó', 'Aprobó', 'Creado'], d.reports.map((r) => [r.folio, r.kind, r.title, S.badge(r.status), r.drafted_by, r.approved_by || '', fmt(r.created_at)]), (i) => open(d.reports[i].id)));
    };
    const create = async () => {
      const fd = await S.get('/engine/findings?status=OPEN');
      const checks = (fd?.findings || []).slice(0, 80).map((f) => ({ f, el: h('input', { type: 'checkbox' }) }));
      const kind = h('select', null, ['DICTAMEN', 'PROVIDENCIA', 'REGULATORIO'].map((k) => h('option', { value: k }, k)));
      const title = h('input'), concl = h('textarea');
      const m = S.modal('Nuevo informe', h('div', null, h('label', null, 'Tipo', kind), h('label', null, 'Título', title), h('label', null, 'Conclusión (mínimo 20 caracteres)', concl),
        h('p', { class: 'muted' }, 'Hallazgos a incluir (abiertos):'), h('div', { class: 'checklist' }, checks.length ? checks.map((c) => h('label', null, c.el, `${c.f.severity} · ${c.f.rule_code} · ${c.f.entity_id}`)) : h('span', { class: 'muted' }, 'No hay hallazgos abiertos.'))));
      m.footer.append(h('button', { class: 'secondary', onclick: () => m.close() }, 'Cancelar'), h('button', { onclick: async () => {
        const r = await S.send('/reports', 'POST', { kind: kind.value, title: title.value, conclusion: concl.value, finding_ids: checks.filter((c) => c.el.checked).map((c) => c.f.id) });
        if (r) { m.close(); S.say('Borrador creado: ' + r.folio, true); draw(); }
      } }, 'Crear borrador'));
    };
    const open = async (id) => {
      const d = await S.get('/reports/' + id);
      if (!d) return;
      const r = d.report;
      const m = S.modal(`${r.folio} — ${r.title}`, h('div', null, h('div', { class: 'kv' }, h('b', null, 'Estado'), S.badge(r.status), h('b', null, 'Redactó'), r.drafted_by, h('b', null, 'Aprobó'), r.approved_by || '—'),
        h('h3', null, 'Hallazgos incluidos'), tbl(['Severidad', 'Regla', 'Entidad', 'Descripción'], (r.body.findings || []).map((f) => [S.badge(f.severity), f.rule_code, f.entity_id, f.message])),
        h('h3', null, 'Conclusión'), h('p', null, r.body.conclusion), r.return_reason ? h('div', { class: 'warn' }, 'Devuelto: ' + r.return_reason) : null,
        r.signer_subject ? h('div', { class: 'okbox' }, 'Firmado por: ' + r.signer_subject + ' · ' + fmt(r.signed_at) + (r.timestamp_embedded ? ' · con sello de tiempo' : ' · sin sello de tiempo (desarrollo)')) : null));
      const post = (label, path, cls, withReason) => h('button', { class: cls || '', onclick: async () => {
        let body = {};
        if (withReason) { const v = await S.ask(label, [{ name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], label); if (!v) return; body = v; }
        if (await S.send(`/reports/${id}/${path}`, 'POST', body)) { m.close(); S.say('Hecho.', true); draw(); }
      } }, label);
      m.footer.append(h('button', { class: 'secondary', onclick: () => S.openFile(`/reports/${id}/preview`, 'vista_previa.pdf') }, 'Vista previa PDF'));
      if (r.status === 'DRAFT' || r.status === 'RETURNED') if (can('report:submit')) m.footer.append(post('Enviar a aprobación', 'submit'));
      if (r.status === 'SUBMITTED' && can('report:approve')) m.footer.append(post('Devolver', 'return', 'danger', true), post('Aprobar', 'approve', 'ok'));
      if (r.status === 'APPROVED' && can('report:sign')) m.footer.append(post('Firmar y sellar', 'sign', 'ok'));
      if (r.status === 'SIGNED') m.footer.append(h('button', { onclick: () => S.openFile(`/reports/${id}/download`, r.folio + '_firmado.pdf') }, 'Abrir PDF firmado'));
      m.footer.append(close(m));
    };
    const verify = async () => {
      const v = await S.ask('Verificar PDF', [{ name: 'file', label: 'Archivo PDF', type: 'file', required: true }], 'Verificar');
      if (!v) return;
      const fd = new FormData(); fd.append('file', v.file);
      const r = await S.upload('/reports/verify', fd);
      if (!r.ok) { S.say(S.err(r)); return; }
      const m = S.modal('Resultado de la verificación', h('div', null, h('p', null, r.data.registered ? 'El documento coincide con uno registrado en SICAS.' : 'El documento NO está registrado en SICAS.'), S.json(r.data.signatures)));
      m.footer.append(close(m));
    };
    draw();
  } });
})();
