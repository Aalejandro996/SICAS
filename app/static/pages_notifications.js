// SICAS-NOTIFICATION-CENTER-20261014-v1
(() => {
  'use strict';
  const S = window.SICAS, { h, can } = S;
  let previousUnreadCount = null;
  let toastTimer = null;

  function showNotificationToast(item) {
    let toast = document.getElementById('notification-toast');
    if (!toast) {
      toast = h('aside', { id: 'notification-toast', class: 'notification-toast hidden', role: 'status', 'aria-live': 'polite' });
      document.body.append(toast);
    }
    const open = h('button', { type: 'button', class: 'secondary', onclick: () => {
      toast.classList.add('hidden'); S.openNotificationCenter('all');
    } }, 'Ver notificación');
    const dismiss = h('button', { type: 'button', class: 'notification-toast-dismiss', 'aria-label': 'Cerrar aviso', onclick: () => toast.classList.add('hidden') }, '×');
    toast.replaceChildren(
      h('div', { class: 'notification-toast-copy' },
        h('strong', null, 'Nueva notificación'),
        h('span', null, item.title),
        h('p', null, item.message)),
      h('div', { class: 'notification-toast-actions' }, open, dismiss));
    toast.classList.remove('hidden');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add('hidden'), 12000);
  }

  S.refreshNotificationCount = async () => {
    if (!S.user) return;
    const response = await S.call('/notifications/unread-count');
    if (!response.ok) return;
    const count = Number(response.data.count || 0);
    const badge = document.getElementById('notification-badge');
    if (badge) {
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.classList.toggle('hidden', count <= 0);
      badge.setAttribute('aria-label', `${count} notificaciones no leídas`);
    }
    if (previousUnreadCount !== null && count > previousUnreadCount) {
      const newest = await S.call('/notifications/?view=unread');
      if (newest.ok && newest.data.notifications && newest.data.notifications.length) {
        showNotificationToast(newest.data.notifications[0]);
      }
    }
    previousUnreadCount = count;
  };

  S.resetNotificationCountState = () => {
    previousUnreadCount = null;
    const badge = document.getElementById('notification-badge');
    if (badge) badge.classList.add('hidden');
    const toast = document.getElementById('notification-toast');
    if (toast) toast.classList.add('hidden');
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
  };

  S.openNotificationCenter = (mode = 'all') => {
    S.notificationCenterMode = mode === 'pending' ? 'pending' : 'all';
    if (location.hash !== '#/notifications') location.hash = '#/notifications';
    else window.dispatchEvent(new Event('hashchange'));
  };

  S.pages.push({
    id: 'notifications', title: 'Notificaciones', perms: [], hiddenFromNav: true,
    render: async (el) => {
      let view = ['all', 'unread', 'pending'].includes(S.notificationCenterMode)
        ? S.notificationCenterMode : 'all';
      const title = h('h2', null, 'Notificaciones');
      const explanation = h('p', { class: 'muted' },
        'Consulta los avisos de informes y solicitudes de rol. “Por atender” reúne los avisos que aún no has marcado como atendidos.');
      const list = h('div', { class: 'notification-list' });
      const state = h('p', { class: 'muted' }, 'Cargando notificaciones…');
      const buttons = {};
      const toolbar = h('div', { class: 'notification-center-toolbar' },
        ...[['all', 'Todas'], ['unread', 'No leídas'], ['pending', 'Por atender']].map(([key, label]) => {
          const button = h('button', { type: 'button', class: 'secondary', onclick: () => { view = key; load(); } }, label);
          buttons[key] = button;
          return button;
        }),
        h('button', { type: 'button', class: 'secondary', onclick: () => load() }, 'Actualizar'));
      el.replaceChildren(h('div', { class: 'notification-center' }, title, explanation, toolbar, state, list));

      function safeInternalPath(path) {
        return typeof path === 'string' && /^#\/[a-zA-Z0-9_/-]+$/.test(path) ? path : '#/notifications';
      }

      async function load() {
        Object.entries(buttons).forEach(([key, button]) => button.classList.toggle('is-active', key === view));
        state.textContent = 'Cargando notificaciones…';
        list.replaceChildren();
        const data = await S.get(`/notifications/?view=${encodeURIComponent(view)}`);
        if (!data) { state.textContent = 'No fue posible cargar la bandeja.'; return; }
        state.textContent = data.notifications.length
          ? `${data.notifications.length} notificación(es) mostradas.`
          : (view === 'pending' ? 'No tienes notificaciones por atender.' : 'No hay notificaciones en esta vista.');
        for (const item of data.notifications) {
          const card = h('article', { class: `notification-item${item.read_at ? '' : ' is-unread'}${item.attended_at ? '' : ' is-unattended'}` });
          const meta = h('div', { class: 'notification-meta' },
            `${item.category === 'REPORT' ? 'Informe' : item.category === 'ROLE' ? 'Solicitud de rol' : 'Sistema'} · ${S.fmt(item.created_at)}`,
            item.read_at ? ' · Leída' : ' · No leída', item.attended_at ? ' · Atendida' : ' · Pendiente de atención');
          const actions = h('div', { class: 'notification-actions' });
          const openButton = h('button', { type: 'button', class: 'secondary', onclick: async () => {
            if (!item.read_at) await S.send(`/notifications/${item.id}/read`, 'POST', {});
            await S.refreshNotificationCount();
            const path = safeInternalPath(item.target_path);
            if (path === '#/notifications') load(); else location.hash = path;
          } }, item.target_path === '#/roles' ? 'Abrir solicitudes de rol' : 'Abrir');
          actions.append(openButton);
          if (!item.read_at) actions.append(h('button', { type: 'button', class: 'secondary', onclick: async () => {
            if (await S.send(`/notifications/${item.id}/read`, 'POST', {})) { await S.refreshNotificationCount(); load(); }
          } }, 'Marcar como leída'));
          if (!item.attended_at) actions.append(h('button', { type: 'button', class: 'ok', onclick: async () => {
            if (await S.send(`/notifications/${item.id}/attend`, 'POST', {})) { await S.refreshNotificationCount(); load(); }
          } }, 'Marcar atendida'));
          card.append(h('div', { class: 'notification-item-header' }, h('h3', null, item.title), meta),
            h('p', { class: 'notification-message' }, item.message), actions);
          list.append(card);
        }
      }
      await load();
    }
  });
})();
