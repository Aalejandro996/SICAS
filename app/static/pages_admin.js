// SICAS — Inicio, usuarios, solicitudes de rol, auditoría del sistema y sistema.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, badge, fmt } = S;

  // ------------------------------------------------------------------ Inicio
  S.pages.push({ id: 'home', title: 'Inicio', perms: [], render: async (el) => {
    el.append(h('h2', null, 'Inicio'));
    const cards = h('div', { class: 'cards' });
    el.append(cards);
    if (can('dashboard:operational', 'dashboard:executive')) {
      const d = await S.get('/analytics/overview');
      if (d) {
        const sev = d.open_findings_by_severity || {};
        ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].forEach((k) => cards.append(S.stat(sev[k] || 0, 'Hallazgos abiertos · ' + S.label(k))));
        const bad = (d.ingestion || []).filter((j) => j.status === 'FAILED').reduce((a, j) => a + j.n, 0);
        cards.append(S.stat(bad, 'Cargas fallidas'));
      }
    }
    if (can('audit:read')) {
      const d = await S.get('/audits');
      if (d) {
        const mine = d.audits.filter((a) => a.status === 'IN_PROGRESS');
        cards.append(S.stat(mine.length, 'Auditorías en curso'));
        el.append(h('h3', null, 'Auditorías en curso'),
          tbl(['Código', 'Unidad', 'Fase', 'Modalidad'], mine.map((a) => [a.code, a.unit_name, S.label2(a.phase), a.modality]),
            (i) => { location.hash = '#/audits/' + mine[i].id; }));
      }
    }
    if (can('audit:report_approve', 'audit:sign_gerente', 'audit:read_final')) {
      const d = await S.get('/audits/final-reports');
      if (d) {
        const pend = d.reports.filter((r) => r.status !== 'SIGNED');
        cards.append(S.stat(pend.length, can('audit:sign_gerente') && !can('audit:report_approve') ? 'Informes por firmar' : 'Informes por atender'));
        el.append(h('h3', null, 'Informes finales'),
          tbl(['Auditoría', 'Unidad', 'Estado', 'Firmas'], d.reports.map((r) => [r.audit_code, r.unit_name, S.badge(r.status), r.signatures + ' / 2']),
            (i) => { location.hash = '#/audits/' + d.reports[i].audit_id + '/informes'; }));
      }
    }
    if (!cards.children.length) el.append(h('div', { class: 'panel' }, 'Bienvenido. Use el menú para acceder a sus módulos.'));
  } });
  S.label2 = (p) => ({ PLANIFICACION: 'Planificación', TRABAJO_CAMPO: 'Trabajo de campo', INFORME: 'Informe' })[p] || p;

  // ------------------------------------------------------------------ Usuarios
  S.pages.push({ id: 'users', title: 'Usuarios', perms: ['user:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Usuarios'));
      const d = await S.get('/admin/users');
      if (!d) return;
      const bar = h('div', { class: 'toolbar' });
      if (can('user:create')) bar.append(h('button', { onclick: newUser }, 'Nuevo usuario'));
      el.append(bar, tbl(['Usuario', 'Nombre', 'Correo', 'Roles', 'Estado', 'Último ingreso', 'Acciones'], d.users.map((u) => [
        u.username, u.full_name, u.email, (u.roles || []).join(', ') || h('span', { class: 'muted' }, 'sin roles'),
        [S.badge(u.is_active ? 'ACTIVE' : 'INACTIVE'), u.locked_until && new Date(u.locked_until) > new Date() ? h('span', { class: 'badge FAILED' }, 'Bloqueado') : null],
        fmt(u.last_login_at),
        h('div', { class: 'actions' },
          can('role:assign') ? h('button', { onclick: () => roleReq(u) }, 'Rol…') : null,
          can('user:unlock') ? h('button', { class: 'secondary', onclick: () => act(u, 'unlock', 'Desbloquear a ' + u.username) }, 'Desbloquear') : null,
          can('user:reset_mfa') ? h('button', { class: 'secondary', onclick: () => act(u, 'reset-mfa', 'Restablecer el MFA de ' + u.username) }, 'Reset MFA') : null,
          can('user:deactivate') ? h('button', { class: u.is_active ? 'danger' : 'ok', onclick: () => act(u, u.is_active ? 'deactivate' : 'activate', (u.is_active ? 'Desactivar a ' : 'Activar a ') + u.username) }, u.is_active ? 'Desactivar' : 'Activar') : null)])));
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
  S.pages.push({ id: 'roles', title: 'Solicitudes de rol', perms: ['role:approve', 'role:assign', 'role:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Solicitudes de cambio de rol'));
      const d = await S.get('/admin/role-requests?status=PENDING');
      if (!d) return;
      el.append(tbl(['Usuario', 'Acción', 'Rol', 'Motivo', 'Solicitó', 'Fecha', ''], d.requests.map((q) => [q.target, S.label(q.action), q.role, q.reason, q.requested_by, fmt(q.created_at),
        can('role:approve') ? h('div', { class: 'actions' }, h('button', { class: 'ok', onclick: () => decide(q, true) }, 'Aprobar'), h('button', { class: 'danger', onclick: () => decide(q, false) }, 'Rechazar')) : ''])));
      if (!d.requests.length) el.append(h('p', { class: 'muted' }, 'No hay solicitudes pendientes.'));
    };
    const decide = async (q, approve) => {
      const v = await S.ask((approve ? 'Aprobar' : 'Rechazar') + ' solicitud', [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }], approve ? 'Aprobar' : 'Rechazar',
        'No puede resolver una solicitud que usted hizo ni una que le afecte (doble control).');
      if (!v) return;
      if (await S.send(`/admin/role-requests/${q.id}/decision`, 'POST', { approve, note: v.note })) { S.say('Registrado.', true); draw(); }
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
