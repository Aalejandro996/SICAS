// SICAS — Herramientas del Administrador del Sistema: monitoreo, certificados, política de seguridad,
// revisión de accesos, sesiones, anulación de auditorías y restauración de respaldos.
// Cada acción del Administrador pide MFA reciente y queda pendiente hasta que el Contralor la aprueba (también con MFA).
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, fmt } = S;
  const ACTION_LABEL = { SECURITY_POLICY: 'Política de seguridad', REVOKE_SESSIONS: 'Cerrar sesiones', DEACTIVATE_USER: 'Desactivar cuenta',
    ACCESS_REVIEW: 'Revisión de accesos', SMTP_TEST: 'Prueba de correo', RESET_PASSWORD: 'Restablecer contraseña' };
  const STATE = { ok: 'Funcionando', down: 'Detenido', unknown: 'Sin datos' };
  const POLICY_LABEL = { max_failed_logins: 'Intentos fallidos antes del bloqueo', lockout_minutes: 'Minutos de bloqueo inicial',
    step_up_seconds: 'Vigencia del MFA reciente (segundos)', session_hours: 'Duración máxima de la sesión (horas)',
    password_max_age_days: 'Vigencia de la contraseña (días; 0 = sin vencimiento)' };
  const TWO_STEPS = 'Doble verificación: se solicita con MFA reciente y se ejecuta solo cuando el Contralor la aprueba.';

  // Solicitud genérica de una acción del Administrador.
  S.requestAdminAction = async (action, payload, title, intro) => {
    const v = await S.ask(title, [{ name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Solicitar',
      (intro ? intro + ' ' : '') + TWO_STEPS);
    if (!v) return null;
    const d = await S.send('/admin/actions', 'POST', { action, payload, reason: v.reason });
    if (d) S.say(d.note, true);
    return d;
  };

  // Contraseña temporal de un restablecimiento aprobado: solo quien lo solicitó y una sola vez.
  S.showTempPassword = async (id) => {
    if (!confirm('La contraseña temporal se muestra UNA sola vez. ¿Mostrarla ahora?')) return false;
    const d = await S.send(`/admin/actions/${id}/secret`, 'POST');
    if (!d) return false;
    const m = S.modal('Contraseña temporal', h('div', null, h('p', null, d.note), h('div', { class: 'temp' }, d.temporary_password)));
    m.footer.append(h('button', { onclick: () => m.close() }, 'Entendido'));
    return true;
  };

  S.myAdminRequests = async (redraw) => {
    const d = await S.get('/admin/actions?status=ALL');
    if (!d) return null;
    return h('div', { class: 'panel' }, h('h3', null, 'Solicitudes del Administrador'),
      tbl(['Fecha', 'Acción', 'Detalle', 'Motivo', 'Solicitó', 'Estado', 'Resolvió', 'Resultado'], d.requests.map((q) => [
        fmt(q.created_at), ACTION_LABEL[q.action] || q.action, q.summary, q.reason, q.requested_by, S.badge(q.status),
        q.decided_by ? `${q.decided_by} (${fmt(q.decided_at)})` : '—',
        q.has_secret && q.requested_by === S.user?.username
          ? h('button', { class: 'sm', onclick: async () => { if (await S.showTempPassword(q.id) && redraw) redraw(); } }, 'Ver contraseña temporal')
          : (q.result ? JSON.stringify(q.result) : '—')])));
  };
  const myRequests = () => S.myAdminRequests();

  // ------------------------------------------------------------------ Monitoreo
  S.pages.push({ id: 'admin-monitor', title: 'Monitoreo', perms: ['health:read'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Monitoreo del sistema'));
      const [m, c, p] = await Promise.all([S.get('/admin/monitor'), S.get('/admin/certificates'), can('param:read') ? S.get('/admin/security-policy') : null]);
      if (m) {
        el.append(
          m.alerts.length ? h('div', { class: 'warn' }, h('b', null, 'Atención: '), m.alerts.join(' ')) : h('div', { class: 'okbox' }, 'Sin alertas: los servicios y respaldos están al día.'),
          h('div', { class: 'cards' },
            S.stat(STATE[m.worker.status], 'Worker · ' + m.worker.detail),
            S.stat(STATE[m.beat.status], 'Planificador (beat) · ' + m.beat.detail),
            S.stat(m.backups.last_ok ? S.date(m.backups.last_ok.started_at) : 'Nunca', 'Último respaldo correcto'),
            S.stat(m.backups.failed_7d, 'Respaldos fallidos (7 días)'),
            S.stat(m.ingestion.failed_7d, 'Cargas fallidas (7 días)'),
            S.stat(m.ingestion.stuck, 'Cargas detenidas')),
          ...(m.backups.last_error ? [h('p', { class: 'muted' }, `Último error de respaldo (${fmt(m.backups.last_error.started_at)}): ${m.backups.last_error.error || '—'}`)] : []));
      }
      if (c) {
        const STATE_C = { VIGENTE: 'ACTIVE', POR_VENCER: 'PENDING', VENCIDO: 'FAILED' };
        el.append(h('h3', null, 'Certificados de firma'),
          h('p', { class: 'muted' }, `Se avisa al titular y a los administradores ${c.warning_days} días antes del vencimiento.`),
          tbl(['Tipo', 'Titular', 'Certificado', 'Vence', 'Días', 'Estado'], c.certificates.map((x) => [
            x.kind === 'PERSONAL' ? 'Personal' : 'Institucional', x.owner, x.subject || x.error || '—', x.not_after ? S.date(x.not_after) : '—',
            x.days_left ?? '—', x.state ? h('span', { class: 'badge ' + STATE_C[x.state] }, x.state.replace('_', ' ').toLowerCase()) : '—'])),
          h('h3', null, 'Firmantes: firma escaneada y certificado'),
          tbl(['Nombre', 'Usuario', 'Roles', 'Firma escaneada', 'Certificado propio'], c.signers.map((u) => [u.full_name, u.username,
            (u.roles || []).map(S.roleLabel).join(', '), u.has_signature ? '✔' : h('b', { class: 'danger-text' }, 'Falta (no puede aprobar ni firmar)'),
            u.has_certificate ? '✔' : 'No (usa el institucional)'])));
      }
      if (p) {
        el.append(h('h3', null, 'Política de seguridad'),
          tbl(['Política', 'Valor vigente', 'Rango'], Object.entries(p.policy).map(([k, v]) => [POLICY_LABEL[k] || k, String(v), `${p.limits[k].min} a ${p.limits[k].max}`])),
          ...(can('param:update') ? [h('div', { class: 'toolbar' }, h('button', { onclick: () => changePolicy(p) }, 'Solicitar cambio de política'),
            h('button', { class: 'secondary', onclick: smtpTest }, 'Solicitar prueba de correo'))] : []));
      }
      if (can('backup:read')) {
        const b = await S.get('/admin/backups');
        const rr = await S.get('/admin/restore-requests');
        if (b) el.append(h('h3', null, 'Respaldos y verificación de restauración'),
          h('p', { class: 'muted' }, 'La verificación comprueba que el archivo existe, que su huella SHA-256 coincide y que pg_restore puede leerlo completo. ' +
            'No sobrescribe la base de producción: la restauración real sigue el procedimiento documentado. ' + TWO_STEPS),
          tbl(['Inicio', 'Estado', 'Tamaño', 'SHA-256', ''], b.backups.map((x) => [fmt(x.started_at), S.badge(x.status),
            x.size_bytes ? (x.size_bytes / 1048576).toFixed(1) + ' MB' : '—', (x.sha256 || '').slice(0, 16),
            x.status === 'OK' && can('backup:restore') ? h('button', { class: 'sm', onclick: () => restore(x) }, 'Solicitar verificación') : ''])));
        if (rr && rr.requests.length) el.append(tbl(['Solicitud', 'Respaldo', 'Motivo', 'Solicitó', 'Estado', 'Verificación'], rr.requests.map((q) => [
          fmt(q.created_at), fmt(q.backup_at), q.reason, q.requested_by, S.badge(q.status),
          q.verify_status ? `${q.verify_status}${q.verify_detail ? ' · ' + JSON.stringify(q.verify_detail) : ''}` : '—'])));
      }
      const mine = await myRequests();
      if (mine) el.append(mine);
    };
    const changePolicy = async (p) => {
      const fields = Object.entries(p.policy).map(([k, v]) => ({ name: k, label: `${POLICY_LABEL[k]} (${p.limits[k].min}-${p.limits[k].max})`, type: 'number', value: String(v) }));
      const v = await S.ask('Cambiar la política de seguridad', [...fields, { name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }],
        'Solicitar', TWO_STEPS);
      if (!v) return;
      const value = Object.fromEntries(Object.keys(p.policy).map((k) => [k, Number(v[k])]));
      const d = await S.send('/admin/actions', 'POST', { action: 'SECURITY_POLICY', payload: { value }, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const smtpTest = async () => {
      const v = await S.ask('Prueba de correo', [{ name: 'to', label: 'Enviar a', type: 'email', required: true },
        { name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Solicitar', TWO_STEPS);
      if (!v) return;
      const d = await S.send('/admin/actions', 'POST', { action: 'SMTP_TEST', payload: { to: v.to }, reason: v.reason });
      if (d) { S.say(d.note, true); draw(); }
    };
    const restore = async (x) => {
      const v = await S.ask('Verificar restauración del respaldo del ' + fmt(x.started_at), [{ name: 'reason', label: 'Motivo (mínimo 15 caracteres)', type: 'textarea', required: true }],
        'Solicitar', TWO_STEPS);
      if (!v) return;
      const d = await S.send(`/admin/backups/${x.id}/restore-request`, 'POST', v);
      if (d) { S.say(d.note, true); draw(); }
    };
    draw();
  } });

  // ------------------------------------------------------------------ Revisión de accesos y sesiones
  S.pages.push({ id: 'access-review', title: 'Revisión de accesos', perms: ['user:read'], render: async (el) => {
    const FLAG = { SIN_USO: 'Sin uso', NUNCA_INGRESO: 'Nunca ingresó', SIN_MFA: 'Sin MFA', SIN_ROLES: 'Sin roles', CONFLICTO_SOD: 'Conflicto SoD' };
    let days = 90;
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Revisión periódica de accesos'),
        h('p', { class: 'muted' }, 'Control trimestral (ISO/IEC 27001 A 5.18 y normativa SUDEASEG): quién tiene qué rol, su último ingreso y las cuentas sin uso. ' +
          'Las desactivaciones y el registro de la revisión siguen la doble verificación (MFA y aprobación del Contralor).'));
      const d = await S.get('/admin/access-review?inactive_days=' + days);
      if (!d) return;
      const sel = h('select', null, [30, 60, 90, 180].map((n) => h('option', { value: n, selected: n === days }, `${n} días`)));
      sel.addEventListener('change', () => { days = Number(sel.value); draw(); });
      const csv = () => {
        const rows = [['Usuario', 'Nombre', 'Activo', 'Roles', 'Último ingreso', 'Días sin uso', 'MFA', 'Observaciones'],
          ...d.users.map((u) => [u.username, u.full_name, u.is_active ? 'Sí' : 'No', (u.roles || []).map(S.roleLabel).join(' / '),
            u.last_login_at || 'Nunca', u.idle_days, u.mfa ? 'Sí' : 'No', u.flags.map((f) => FLAG[f]).join(' / ')])];
        const text = rows.map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(';')).join('\r\n');
        S.download(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }), `revision_accesos_${new Date().toISOString().slice(0, 10)}.csv`);
      };
      const s = d.summary;
      el.append(h('div', { class: 'toolbar' }, h('label', null, 'Sin uso desde', sel), h('button', { class: 'secondary', onclick: csv }, 'Exportar CSV'),
        can('user:update') ? h('button', { onclick: async () => {
          const v = await S.ask('Registrar la revisión de accesos', [{ name: 'note', label: 'Conclusiones de la revisión', type: 'textarea' },
            { name: 'reason', label: 'Motivo (mínimo 10 caracteres)', type: 'textarea', required: true }], 'Solicitar', TWO_STEPS);
          if (!v) return;
          const r = await S.send('/admin/actions', 'POST', { action: 'ACCESS_REVIEW', payload: { inactive_days: days, note: v.note }, reason: v.reason });
          if (r) S.say(r.note, true);
        } }, 'Registrar revisión como evidencia') : null),
      h('div', { class: 'cards' }, S.stat(s.active, 'Cuentas activas'), S.stat(s.idle, `Sin uso ≥ ${days} días`), S.stat(s.without_mfa, 'Sin MFA'), S.stat(s.sod_conflicts, 'Conflictos SoD')),
      tbl(['Usuario', 'Nombre', 'Roles', 'Último ingreso', 'Días sin uso', 'Observaciones', ''], d.users.map((u) => [u.username, u.full_name,
        (u.roles || []).map(S.roleLabel).join(', ') || '—', u.last_login_at ? fmt(u.last_login_at) : 'Nunca', u.idle_days,
        u.flags.length ? u.flags.map((f) => h('span', { class: 'badge PENDING' }, FLAG[f])) : '—',
        h('div', { class: 'actions' },
          u.is_active && can('user:deactivate') && u.flags.length ? h('button', { class: 'sm danger', onclick: () => S.requestAdminAction('DEACTIVATE_USER', { user_id: u.id },
            'Proponer desactivar a ' + u.username, 'La cuenta se desactiva (reversible) y se cierran sus sesiones.') }, 'Proponer desactivación') : null)])));
      if (can('session:revoke')) {
        const ss = await S.get('/admin/sessions');
        if (ss) el.append(h('h3', null, 'Sesiones activas'),
          tbl(['Usuario', 'Nombre', 'Sesiones', 'Desde', 'Última actividad', 'Vence', ''], ss.sessions.map((x) => [x.username, x.full_name, x.sessions,
            fmt(x.since), fmt(x.last_activity), fmt(x.expires_at),
            h('button', { class: 'sm danger', onclick: () => S.requestAdminAction('REVOKE_SESSIONS', { user_id: x.user_id }, 'Cerrar las sesiones de ' + x.username,
              'Las sesiones se cierran al vencer el acceso vigente (máximo 10 minutos).') }, 'Cerrar sesiones')])));
      }
      const hist = await S.get('/admin/access-reviews');
      if (hist && hist.reviews.length) el.append(h('h3', null, 'Revisiones registradas'),
        tbl(['Fecha', 'Realizó', 'Sin uso desde', 'Cuentas activas', 'Sin uso', 'Sin MFA', 'Conclusiones'], hist.reviews.map((r) => [fmt(r.performed_at), r.performed_by,
          r.inactive_days + ' días', r.summary?.active ?? '—', r.summary?.idle ?? '—', r.summary?.without_mfa ?? '—', r.note || '—'])));
    };
    draw();
  } });

  // ------------------------------------------------------------------ Anulación de auditorías
  S.pages.push({ id: 'annulments', title: 'Anulación de auditorías', perms: ['audit:annul_request'], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Anulación de auditorías creadas por error'),
        h('p', { class: 'muted' }, 'Solo se anulan auditorías en curso y sin informes generados. La auditoría no se borra: queda anulada, fuera de las listas y con su código liberado, ' +
          'y la anulación queda en la bitácora. ' + TWO_STEPS));
      const code = h('input', { placeholder: 'S-SC-005-2026-A3' });
      const found = h('div');
      el.append(h('div', { class: 'toolbar' }, h('label', null, 'Código de la auditoría', code), h('button', { onclick: async () => {
        const d = await S.get('/admin/audits/lookup?code=' + encodeURIComponent(code.value.trim()));
        if (!d) return found.replaceChildren();
        const a = d.audit;
        found.replaceChildren(h('div', { class: 'panel' }, h('div', { class: 'kv' }, h('b', null, 'Código'), a.code, h('b', null, 'Expediente'), a.file_code,
          h('b', null, 'Unidad'), a.unit_name, h('b', null, 'Estado'), S.badge(a.status), h('b', null, 'Fase'), S.label2 ? S.label2(a.phase) : a.phase,
          h('b', null, 'Informes'), String(a.reports)),
          a.status === 'IN_PROGRESS' && !a.reports ? h('button', { class: 'danger', onclick: async () => {
            const v = await S.ask('Solicitar la anulación de ' + a.code, [{ name: 'reason', label: 'Justificación (mínimo 15 caracteres)', type: 'textarea', required: true }],
              'Solicitar', TWO_STEPS);
            if (!v) return;
            const r = await S.send('/admin/audit-annulments', 'POST', { code: a.code, reason: v.reason });
            if (r) { S.say(r.note, true); draw(); }
          } }, 'Solicitar anulación') : h('div', { class: 'warn' }, 'No se puede anular: debe estar en curso y sin informes.')));
      } }, 'Buscar')), found);
      const all = [];
      for (const st of ['PENDING', 'APPROVED', 'REJECTED']) { const x = await S.get('/admin/audit-annulments?status=' + st); if (x) all.push(...x.requests); }
      el.append(h('h3', null, 'Solicitudes'), tbl(['Fecha', 'Auditoría', 'Justificación', 'Solicitó', 'Estado', 'Resolvió', 'Nota'], all.map((q) => [
        fmt(q.created_at), q.audit_code, q.reason, q.requested_by, S.badge(q.status), q.decided_by ? `${q.decided_by} (${fmt(q.decided_at)})` : '—', q.decision_note || '—'])));
    };
    draw();
  } });

  // ------------------------------------------------------------------ Bandeja de aprobación del Contralor (se usa en «Solicitudes»)
  S.adminApprovals = async (el, redraw) => {
    const decide = async (path, title, approve, intro) => {
      const v = await S.ask((approve ? 'Aprobar: ' : 'Rechazar: ') + title, [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }],
        approve ? 'Aprobar' : 'Rechazar', intro);
      if (!v) return;
      const r = await S.send(path, 'POST', { approve, note: v.note });
      if (r) { S.say(r.status === 'FAILED' ? 'No se pudo ejecutar: ' + JSON.stringify(r.result) : 'Registrado.', r.status !== 'FAILED'); redraw(); }
    };
    const buttons = (path, title, intro) => h('div', { class: 'actions' },
      h('button', { class: 'ok', onclick: () => decide(path, title, true, intro) }, 'Aprobar'),
      h('button', { class: 'danger', onclick: () => decide(path, title, false) }, 'Rechazar'));
    if (can('admin:action_approve')) {
      const a = await S.get('/admin/actions?status=PENDING');
      if (a) el.append(h('h3', null, 'Acciones del Administrador del Sistema'),
        h('p', { class: 'muted' }, 'Segunda verificación: al aprobar, la acción se ejecuta de inmediato.'),
        tbl(['Fecha', 'Acción', 'Detalle', 'Motivo', 'Solicitó', ''], a.requests.map((q) => [fmt(q.created_at), ACTION_LABEL[q.action] || q.action, q.summary,
          q.reason, q.requested_by, q.requested_by === S.user?.username ? 'Propia' : buttons(`/admin/actions/${q.id}/decision`, ACTION_LABEL[q.action] || q.action)])));
    }
    if (can('audit:annul_approve')) {
      const a = await S.get('/admin/audit-annulments?status=PENDING');
      if (a) el.append(h('h3', null, 'Anulación de auditorías'),
        tbl(['Fecha', 'Auditoría', 'Justificación', 'Solicitó', ''], a.requests.map((q) => [fmt(q.created_at), q.audit_code, q.reason, q.requested_by,
          buttons(`/admin/audit-annulments/${q.id}/decision`, 'anular ' + q.audit_code, 'La auditoría queda anulada y fuera de las listas; su código se libera.')])));
    }
    if (can('backup:restore_approve')) {
      const a = await S.get('/admin/restore-requests');
      const pending = a ? a.requests.filter((q) => q.status === 'PENDING') : [];
      if (a) el.append(h('h3', null, 'Verificación de restauración de respaldos'),
        tbl(['Fecha', 'Respaldo', 'Motivo', 'Solicitó', ''], pending.map((q) => [fmt(q.created_at), fmt(q.backup_at), q.reason, q.requested_by,
          buttons(`/admin/restore-requests/${q.id}/decision`, 'verificar el respaldo del ' + fmt(q.backup_at))])));
    }
  };
})();
