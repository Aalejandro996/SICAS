// SICAS — Registro explícito de actividad de auditoría.
(() => {
  'use strict';
  const S = window.SICAS, { h, can, tbl } = S;
  const duration = (seconds) => {
    const n = Math.max(0, Math.floor(Number(seconds || 0)));
    const hours = Math.floor(n / 3600), minutes = Math.floor((n % 3600) / 60), secs = n % 60;
    return `${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
  };
  S.pages.push({
    id: 'auditor-activity', title: 'Registro de actividad', perms: ['audit:manage'],
    render: async (el) => {
      el.append(h('h2', null, 'Registro de actividad del auditor'),
        h('p', { class: 'muted' }, 'Registra tiempo activo declarado mediante inicio, pausa, reanudación y finalización. El registro no mide teclas ni demuestra por sí solo productividad; pausa el cronómetro durante descansos y otras tareas.'));
      const target = h('div', { class: 'ctl-activity-host' }, h('p', { class: 'muted' }, 'Cargando auditorías asignadas…'));
      el.append(target);
      let timerInterval = null;
      async function load() {
        if (timerInterval !== null) { clearInterval(timerInterval); timerInterval = null; }
        const data = await S.get('/analytics/activity/options');
        if (!data) return;
        const current = data.current;
        const timerText = current ? h('p', { class: 'ctl-activity-timer' }, duration(current.elapsed_seconds)) : null;
        if (current && current.status === 'RUNNING') {
          const baseSeconds = Number(current.elapsed_seconds || 0);
          const loadedAt = Date.now();
          timerInterval = setInterval(() => {
            if (!timerText || !timerText.isConnected) {
              clearInterval(timerInterval);
              timerInterval = null;
              return;
            }
            timerText.textContent = duration(baseSeconds + Math.floor((Date.now() - loadedAt) / 1000));
          }, 1000);
        }
        const auditSelect = h('select', null,
          h('option', { value: '' }, 'Seleccione una auditoría asignada'),
          data.audits.map((a) => h('option', { value: a.audit_id }, `${a.code} — ${a.audit_domain} — ${a.unit_name} — ${a.phase}`)));
        const statusCard = current
          ? h('div', { class: 'ctl-activity-current' },
              h('h3', null, `${current.audit_code} · ${current.audit_domain}`),
              h('p', null, `${current.unit_name} · Fase ${current.phase}`),
              timerText,
              h('p', { class: 'muted' }, `Estado: ${current.status === 'RUNNING' ? 'En ejecución' : 'Pausada'} · Inicio ${String(current.started_at).replace('T',' ').slice(0,19)} UTC`),
              h('div', { class: 'actions' },
                current.status === 'RUNNING'
                  ? h('button', { onclick: async () => { if (await S.send('/analytics/activity/pause', 'POST', {})) { S.say('Cronómetro pausado.', true); await load(); } } }, 'Pausar')
                  : h('button', { onclick: async () => { if (await S.send('/analytics/activity/resume', 'POST', {})) { S.say('Cronómetro reanudado.', true); await load(); } } }, 'Reanudar'),
                h('button', { class: 'secondary', onclick: async () => {
                  if (!confirm('¿Finalizar esta sesión y guardar el tiempo activo acumulado?')) return;
                  if (await S.send('/analytics/activity/stop', 'POST', {})) { S.say('Sesión finalizada y guardada.', true); await load(); }
                } }, 'Finalizar sesión')))
          : h('div', { class: 'ctl-activity-current' },
              h('p', null, 'No hay una sesión de actividad activa.'),
              h('label', null, 'Auditoría', auditSelect),
              h('button', { onclick: async () => {
                if (!auditSelect.value) { S.say('Selecciona una auditoría asignada.'); return; }
                if (await S.send('/analytics/activity/start', 'POST', { audit_id: auditSelect.value })) { S.say('Cronómetro iniciado.', true); await load(); }
              } }, 'Iniciar actividad'));
        const recentRows = (data.recent_sessions || []).map((r) => [r.audit_code, r.started_at ? String(r.started_at).replace('T',' ').slice(0,19) + ' UTC' : '—',
          r.ended_at ? String(r.ended_at).replace('T',' ').slice(0,19) + ' UTC' : 'En curso',
          r.status === 'RUNNING' ? 'En ejecución' : r.status === 'PAUSED' ? 'Pausada' : 'Finalizada', duration(r.elapsed_seconds == null ? r.accumulated_seconds : r.elapsed_seconds)]);
        target.replaceChildren(statusCard,
          h('section', { class: 'panel' }, h('h3', null, 'Últimas sesiones registradas'),
            h('p', { class: 'muted' }, 'Las horas del dashboard suman las sesiones que comenzaron dentro del período seleccionado. Las sesiones finalizadas quedan históricas e inmutables.'),
            recentRows.length ? tbl(['Auditoría', 'Inicio (UTC)', 'Fin (UTC)', 'Estado', 'Tiempo activo'], recentRows) : h('p', { class: 'muted' }, 'Todavía no hay sesiones registradas.')));
      }
      await load();
    }
  });
})();
