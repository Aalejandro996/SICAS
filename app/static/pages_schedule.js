// SICAS — Horario laboral (lunes a viernes, 8:00 a 17:00, hora de Venezuela, sin feriados) y horas extras.
// Aviso 15 minutos antes del cierre, pantalla de bloqueo fuera de horario, solicitud y aprobación de horas
// extras (Jefe -> Gerencia -> Contralor) y panel del Administrador del Sistema.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl, fmt } = S;
  const OT_STATE = { PENDING_JEFE: 'Pendiente del Jefe', PENDING_GERENCIA: 'Pendiente de Gerencia', PENDING_CONTRALOR: 'Pendiente del Contralor',
    APPROVED: 'Aprobada', REJECTED: 'Rechazada', CANCELLED: 'Cancelada' };
  const OT_BADGE = { PENDING_JEFE: 'PENDING', PENDING_GERENCIA: 'PENDING', PENDING_CONTRALOR: 'PENDING', APPROVED: 'ACTIVE', REJECTED: 'REJECTED', CANCELLED: 'INACTIVE' };
  const hm = (v) => (v ? new Date(v).toLocaleString('es-VE', { timeZone: 'America/Caracas', dateStyle: 'short', timeStyle: 'short' }) : '—');
  const otBadge = (st) => h('span', { class: 'badge ' + (OT_BADGE[st] || '') }, OT_STATE[st] || st);

  // ------------------------------------------------------------------ aviso y bloqueo
  let banner = null, lastWarned = null;
  const showBanner = (text, level) => {
    if (!banner) {
      banner = h('div', { class: 'schedule-banner', role: 'status', 'aria-live': 'polite' });
      document.body.append(banner);
    }
    banner.className = 'schedule-banner ' + (level || '');
    banner.textContent = text;
    banner.hidden = !text;
  };

  S.onOutsideHours = (data) => {
    if (document.querySelector('.overlay.outside-hours')) return;
    showBanner('');
    const m = S.modal('Fuera del horario laboral', h('div', null,
      h('p', null, data.error || 'SICAS está disponible de lunes a viernes de 8:00 a 17:00 (hora de Venezuela), excepto feriados.'),
      data.next_open ? h('p', null, h('b', null, 'Próxima apertura: '), hm(data.next_open)) : null,
      h('p', { class: 'muted' }, 'Para trabajar fuera de ese horario, solicite horas extras dentro del horario laboral. Las aprueban el Jefe de Auditoría, Gerencia y el Contralor.')));
    m.overlay.classList.add('outside-hours');
    m.footer.append(h('button', { onclick: async () => { await S.call('/auth/logout', { method: 'POST', json: {} }); location.reload(); } }, 'Salir'));
  };

  const checkSchedule = async () => {
    if (!S.user) return;
    const r = await S.call('/schedule/status');
    if (!r.ok) return;
    const st = r.data;
    if (st.exempt) { showBanner(''); return; }
    if (st.blocked) { S.onOutsideHours({ next_open: st.next_open }); return; }
    if (st.minutes_left <= st.warning_minutes) {
      const what = st.overtime ? 'Sus horas extras terminan' : 'SICAS se bloquea por fin del horario laboral';
      showBanner(`${what} en ${st.minutes_left} minuto(s) (${hm(st.closes_at)}). Guarde su trabajo.`, 'warning');
      const key = st.closes_at;
      if (lastWarned !== key) { lastWarned = key; S.say(`Atención: ${what.toLowerCase()} en ${st.minutes_left} minuto(s).`); }
    } else {
      showBanner(st.overtime ? `Trabajando en horas extras hasta ${hm(st.overtime.ends_at)}.` : '', 'info');
    }
  };
  S.startScheduleWatch = () => {
    checkSchedule();
    if (!S.scheduleTimer) { S.scheduleTimer = setInterval(checkSchedule, 60000); S.timers.push(S.scheduleTimer); }
  };

  // ------------------------------------------------------------------ calendario de feriados
  const holidayTable = async (year, withActions) => {
    const d = await S.get('/schedule/holidays?year=' + year);
    if (!d) return h('div');
    const KIND = { FIXED: 'Fijo', MOVABLE: 'Móvil (Carnaval / Semana Santa)', DECREE: 'Decretado' };
    return tbl(['Fecha', 'Día', 'Feriado', 'Tipo', 'Estado', ...(withActions ? [''] : [])], d.holidays.map((x) => {
      const dt = new Date(x.holiday_date + 'T12:00:00');
      return [dt.toLocaleDateString('es-VE'), dt.toLocaleDateString('es-VE', { weekday: 'long' }), x.name, KIND[x.kind] || x.kind,
        x.observed ? 'No laborable' : h('b', null, 'Laborable (no se observa)'),
        ...(withActions ? [can('param:update') && S.requestAdminAction ? h('button', { class: 'sm secondary', onclick: () => S.requestAdminAction('HOLIDAY',
          { date: x.holiday_date, name: x.name, observed: !x.observed }, (x.observed ? 'Declarar laborable el ' : 'Declarar no laborable el ') + dt.toLocaleDateString('es-VE')) },
        x.observed ? 'Declarar laborable' : 'Declarar no laborable') : ''] : [])];
    }));
  };

  // ------------------------------------------------------------------ horas extras (usuarios y aprobadores)
  S.pages.push({ id: 'overtime', title: 'Horas extras', perms: [], render: async (el) => {
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Horario laboral y horas extras'));
      const st = await S.get('/schedule/status');
      if (!st) return;
      el.append(h('div', { class: 'panel' }, h('b', null, st.schedule), h('p', { class: 'muted' }, st.exempt
        ? 'Su rol no está sujeto al horario laboral.'
        : (st.open ? `Abierto: cierra a las ${hm(st.closes_at)}.` : `Cerrado. Próxima apertura: ${hm(st.next_open)}.`)
          + (st.holiday ? ` Hoy es feriado: ${st.holiday}.` : ''))));
      if (!st.exempt) {
        const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Caracas' });
        const day = h('input', { type: 'date', value: today, min: today }), from = h('input', { type: 'time', value: '17:00' }), to = h('input', { type: 'time', value: '19:00' });
        const reason = h('textarea', { placeholder: 'Cierre de la auditoría, entrega de informe…' });
        el.append(h('div', { class: 'panel' }, h('h3', null, 'Solicitar horas extras'),
          h('p', { class: 'muted' }, 'Hasta 12 horas por solicitud y con hasta 30 días de anticipación. La aprueban, en orden, el Jefe de Auditoría de su área (si lo hay), Gerencia y el Contralor.'),
          h('div', { class: 'toolbar' }, h('label', null, 'Día', day), h('label', null, 'Desde', from), h('label', null, 'Hasta', to)),
          h('label', null, 'Motivo (mínimo 10 caracteres)', reason),
          h('div', { class: 'toolbar' }, h('button', { onclick: async (e) => {
            let end = `${day.value}T${to.value}`;
            if (to.value <= from.value) { const n = new Date(day.value + 'T12:00:00'); n.setDate(n.getDate() + 1); end = `${n.toLocaleDateString('en-CA')}T${to.value}`; }
            await S.busy(e.target, async () => {
              const r = await S.send('/schedule/overtime', 'POST', { starts_at: `${day.value}T${from.value}`, ends_at: end, reason: reason.value.trim() });
              if (r) { S.say(r.note, true); draw(); }
            });
          } }, 'Solicitar'))));
        const mine = await S.get('/schedule/overtime?scope=mine');
        if (mine) el.append(h('h3', null, 'Mis solicitudes'), tbl(['Desde', 'Hasta', 'Motivo', 'Estado', 'Aprobaciones', ''], mine.requests.map((q) => [
          hm(q.starts_at), hm(q.ends_at), q.reason, otBadge(q.status),
          [q.jefe_name && `Jefe: ${q.jefe_name}`, q.gerente_name && `Gerencia: ${q.gerente_name}`, q.contralor_name && `Contralor: ${q.contralor_name}`,
            q.rejected_name && `Rechazó: ${q.rejected_name}${q.reject_note ? ' (' + q.reject_note + ')' : ''}`].filter(Boolean).join(' · ') || '—',
          !['REJECTED', 'CANCELLED'].includes(q.status) && new Date(q.ends_at) > new Date() ? h('button', { class: 'sm secondary', onclick: async () => {
            if (confirm('¿Cancelar esta solicitud?') && await S.send(`/schedule/overtime/${q.id}/cancel`, 'POST')) draw();
          } }, 'Cancelar') : ''])));
      }
      const pending = await S.get('/schedule/overtime?scope=pending');
      if (pending && pending.requests.length) {
        const decide = async (q, approve) => {
          const v = await S.ask((approve ? 'Aprobar' : 'Rechazar') + ' horas extras de ' + q.full_name, [{ name: 'note', label: 'Nota (opcional)', type: 'textarea' }],
            approve ? 'Aprobar' : 'Rechazar', `${hm(q.starts_at)} a ${hm(q.ends_at)}. ${q.reason}`);
          if (v && await S.send(`/schedule/overtime/${q.id}/decision`, 'POST', { approve, note: v.note })) { S.say('Registrado.', true); draw(); }
        };
        el.append(h('h3', null, 'Solicitudes por aprobar'), tbl(['Solicitante', 'Desde', 'Hasta', 'Motivo', 'Etapa', ''], pending.requests.map((q) => [
          q.full_name, hm(q.starts_at), hm(q.ends_at), q.reason, otBadge(q.status),
          h('div', { class: 'actions' }, h('button', { class: 'sm ok', onclick: () => decide(q, true) }, 'Aprobar'), h('button', { class: 'sm danger', onclick: () => decide(q, false) }, 'Rechazar'))])));
      }
      el.append(h('h3', null, `Feriados ${new Date().getFullYear()}`), await holidayTable(new Date().getFullYear(), false));
    };
    draw();
  } });

  // ------------------------------------------------------------------ panel del Administrador del Sistema
  S.pages.push({ id: 'work-schedule', title: 'Horario laboral', perms: ['health:read'], render: async (el) => {
    let year = new Date().getFullYear();
    const draw = async () => {
      el.replaceChildren(h('h2', null, 'Horario laboral y horas extras'),
        h('p', { class: 'muted' }, 'Lunes a viernes de 8:00 a 17:00 (hora de Venezuela), excepto feriados. No aplica al Administrador del Sistema, Gerencia ni al Contralor. ' +
          'Fuera del horario solo trabaja quien tenga horas extras aprobadas por el Jefe de Auditoría, Gerencia y el Contralor. Las tareas automáticas siguen corriendo las 24 horas.'));
      const all = await S.get('/schedule/overtime?scope=all');
      if (all) el.append(h('h3', null, 'Registro de horas extras'), tbl(['Solicitante', 'Desde', 'Hasta', 'Horas', 'Motivo', 'Estado', 'Jefe', 'Gerencia', 'Contralor', 'Uso'],
        all.requests.map((q) => [q.full_name, hm(q.starts_at), hm(q.ends_at), ((new Date(q.ends_at) - new Date(q.starts_at)) / 3600000).toFixed(1), q.reason, otBadge(q.status),
          q.jefe_name ? `${q.jefe_name} (${hm(q.jefe_at)})` : '—', q.gerente_name ? `${q.gerente_name} (${hm(q.gerente_at)})` : '—',
          q.contralor_name ? `${q.contralor_name} (${hm(q.contralor_at)})` : (q.rejected_name ? `Rechazó ${q.rejected_name}` : '—'),
          q.first_used_at ? `${hm(q.first_used_at)} – ${hm(q.last_used_at)}` : 'Sin uso'])));
      const ysel = h('select', null, [year - 1, year, year + 1].map((y) => h('option', { value: y, selected: y === year }, String(y))));
      ysel.addEventListener('change', () => { year = Number(ysel.value); draw(); });
      el.append(h('h3', null, 'Calendario de feriados'),
        h('p', { class: 'muted' }, 'Fijos y móviles (Carnaval, Jueves y Viernes Santo) se calculan solos. Los decretados por el Ejecutivo, o un feriado que no se observe, ' +
          'se cargan con doble verificación (MFA y aprobación del Contralor).'),
        h('div', { class: 'toolbar' }, h('label', null, 'Año', ysel),
          can('param:update') && S.requestAdminAction ? h('button', { onclick: async () => {
            const v = await S.ask('Proponer día no laborable decretado', [{ name: 'date', label: 'Fecha', type: 'date', required: true },
              { name: 'name', label: 'Motivo o decreto (p. ej. Decreto N° … Gaceta Oficial …)', required: true }], 'Continuar');
            if (v) S.requestAdminAction('HOLIDAY', { date: v.date, name: v.name, observed: true }, 'Declarar no laborable el ' + v.date);
          } }, 'Proponer feriado decretado') : null),
        await holidayTable(year, true));
    };
    draw();
  } });
})();
