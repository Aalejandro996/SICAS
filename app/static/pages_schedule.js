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

  // ------------------------------------------------------------------ calendario de feriados (interactivo)
  const KIND = { FIXED: 'Fijo', MOVABLE: 'Móvil (Carnaval / Semana Santa)', DECREE: 'Decretado' };
  const MONTHS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const longDate = (s) => new Date(s + 'T12:00:00').toLocaleDateString('es-VE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const caracasToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Caracas' });
  const holidayCache = {};
  const loadHolidays = async (year) => {
    if (!holidayCache[year]) {
      const d = await S.get('/schedule/holidays?year=' + year);
      if (!d) return null;
      holidayCache[year] = Object.fromEntries(d.holidays.map((x) => [x.holiday_date, x]));
    }
    return holidayCache[year];
  };

  // Calendario anual: cada mes en su cuadrícula; un clic en un día muestra si es laborable y, al Administrador,
  // las acciones (con doble verificación) para declarar un feriado decretado o un feriado no observado.
  const holidayCalendar = (initialYear, withActions) => {
    const root = h('div', { class: 'holiday-cal' });
    // month = null: vista anual; 0..11: un solo mes. En pantallas angostas abre en el mes actual.
    let year = initialYear, month = window.innerWidth < 700 && initialYear === Number(caracasToday().slice(0, 4)) ? Number(caracasToday().slice(5, 7)) - 1 : null;
    const canAct = withActions && can('param:update') && S.requestAdminAction;

    const dayInfo = (date, hol) => {
      const wd = new Date(date + 'T12:00:00').getDay();
      if (hol && hol.observed) return { cls: 'hol hol-' + hol.kind.toLowerCase(), text: hol.name };
      if (hol && !hol.observed) return { cls: 'hol-off', text: hol.name + ' (no se observa: laborable)' };
      if (wd === 0 || wd === 6) return { cls: 'weekend', text: 'Fin de semana' };
      return { cls: '', text: 'Laborable de 8:00 a 17:00' };
    };

    const openDay = (date, hol) => {
      const wd = new Date(date + 'T12:00:00').getDay();
      const weekend = wd === 0 || wd === 6;
      const status = hol ? (hol.observed ? 'No laborable (feriado)' : 'Laborable: el feriado no se observa') : weekend ? 'No laborable (fin de semana)' : 'Laborable de 8:00 a 17:00';
      const m = S.modal(longDate(date), h('div', null, h('dl', { class: 'kv' },
        h('dt', null, 'Estado'), h('dd', null, status),
        ...(hol ? [h('dt', null, 'Feriado'), h('dd', null, hol.name), h('dt', null, 'Tipo'), h('dd', null, KIND[hol.kind] || hol.kind)] : [])),
        canAct ? h('p', { class: 'muted' }, 'Los cambios piden su código MFA y se aplican cuando el Contralor los aprueba.') : null));
      if (canAct && hol) {
        m.footer.append(h('button', { class: 'secondary', onclick: async () => {
          m.close();
          await S.requestAdminAction('HOLIDAY', { date, name: hol.name, observed: !hol.observed },
            (hol.observed ? 'Declarar laborable el ' : 'Declarar no laborable el ') + longDate(date));
        } }, hol.observed ? 'Declarar laborable' : 'Declarar no laborable'));
      } else if (canAct && !weekend) {
        m.footer.append(h('button', { onclick: async () => {
          const v = await S.ask('Proponer día no laborable decretado', [{ name: 'name', label: 'Motivo o decreto (p. ej. Decreto N° … Gaceta Oficial …)', required: true }],
            'Continuar', longDate(date));
          m.close();
          if (v) await S.requestAdminAction('HOLIDAY', { date, name: v.name, observed: true }, 'Declarar no laborable el ' + longDate(date));
        } }, 'Proponer feriado decretado'));
      }
      m.footer.append(h('button', { class: 'secondary', onclick: () => m.close() }, 'Cerrar'));
    };

    const monthGrid = (hols, m, big) => {
      const today = caracasToday();
      const first = new Date(year, m, 1), days = new Date(year, m + 1, 0).getDate();
      const lead = (first.getDay() + 6) % 7;     // semana de lunes a domingo
      const cells = [...WEEKDAYS.map((w) => h('span', { class: 'wd', 'aria-hidden': 'true' }, w)), ...Array.from({ length: lead }, () => h('span', { class: 'pad' }))];
      for (let d = 1; d <= days; d++) {
        const date = iso(year, m, d), hol = hols[date], info = dayInfo(date, hol);
        cells.push(h('button', { type: 'button', class: `day ${info.cls}${date === today ? ' today' : ''}`, title: `${longDate(date)}: ${info.text}`,
          'aria-label': `${longDate(date)}: ${info.text}`, onclick: () => openDay(date, hol) },
          h('span', { class: 'n' }, String(d)), big && hol ? h('span', { class: 'lbl' }, hol.name) : null));
      }
      const count = Object.keys(hols).filter((k) => k.startsWith(`${year}-${pad(m + 1)}`) && hols[k].observed).length;
      return h('div', { class: 'month' + (big ? ' big' : '') },
        h('button', { type: 'button', class: 'mname', title: big ? 'Volver al año' : 'Ver el mes', onclick: () => { month = big ? null : m; draw(); } },
          MONTHS[m], count ? h('span', { class: 'cnt' }, String(count)) : null),
        h('div', { class: 'grid' }, cells));
    };

    const draw = async () => {
      const hols = await loadHolidays(year);
      if (!hols) return;
      const step = (delta) => () => {
        if (month === null) year += delta;
        else { month += delta; if (month < 0) { month = 11; year -= 1; } if (month > 11) { month = 0; year += 1; } }
        year = Math.min(2045, Math.max(2015, year)); draw();
      };
      const today = caracasToday();
      const upcoming = Object.values(hols).filter((x) => x.observed && x.holiday_date >= today).slice(0, 4);
      const list = h('details', { class: 'hol-list' }, h('summary', null, `Ver los feriados de ${year} como lista`),
        tbl(['Fecha', 'Feriado', 'Tipo', 'Estado'], Object.values(hols).map((x) => [longDate(x.holiday_date), x.name, KIND[x.kind] || x.kind,
          x.observed ? 'No laborable' : h('b', null, 'Laborable (no se observa)')])));
      root.replaceChildren(...[
        h('div', { class: 'cal-bar' },
          h('button', { type: 'button', class: 'secondary sm', 'aria-label': 'Anterior', onclick: step(-1) }, '‹'),
          h('b', { class: 'cal-title' }, month === null ? String(year) : `${MONTHS[month]} ${year}`),
          h('button', { type: 'button', class: 'secondary sm', 'aria-label': 'Siguiente', onclick: step(1) }, '›'),
          h('button', { type: 'button', class: 'secondary sm', onclick: () => { year = Number(today.slice(0, 4)); month = month === null ? null : Number(today.slice(5, 7)) - 1; draw(); } }, 'Hoy'),
          month !== null ? h('button', { type: 'button', class: 'secondary sm', onclick: () => { month = null; draw(); } }, 'Ver el año') : null),
        h('div', { class: 'cal-legend' }, ...[['hol hol-fixed', 'Feriado fijo'], ['hol hol-movable', 'Carnaval / Semana Santa'], ['hol hol-decree', 'Decretado'],
          ['hol-off', 'Feriado no observado (laborable)'], ['weekend', 'Fin de semana'], ['today', 'Hoy']].map(([c, t]) => h('span', null, h('i', { class: 'sw ' + c }), t))),
        upcoming.length && month === null && year === Number(today.slice(0, 4))
          ? h('p', { class: 'muted' }, 'Próximos: ' + upcoming.map((x) => `${new Date(x.holiday_date + 'T12:00:00').toLocaleDateString('es-VE', { day: 'numeric', month: 'short' })} ${x.name}`).join(' · ')) : null,
        month === null ? h('div', { class: 'months' }, Array.from({ length: 12 }, (_, m) => monthGrid(hols, m, false))) : monthGrid(hols, month, true),
        h('p', { class: 'muted' }, canAct ? 'Haga clic en un día para ver su estado o proponer un cambio. Clic en el nombre del mes para ampliarlo.' : 'Haga clic en un día para ver su estado. Clic en el nombre del mes para ampliarlo.'),
        list].filter(Boolean));
    };
    draw();
    return root;
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
      el.append(h('h3', null, 'Calendario de feriados'), holidayCalendar(new Date().getFullYear(), false));
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
      el.append(h('h3', null, 'Calendario de feriados'),
        h('p', { class: 'muted' }, 'Fijos y móviles (Carnaval, Jueves y Viernes Santo) se calculan solos. Los decretados por el Ejecutivo, o un feriado que no se observe, ' +
          'se cargan con doble verificación (MFA y aprobación del Contralor).'),
        holidayCalendar(year, true));
    };
    draw();
  } });
})();
