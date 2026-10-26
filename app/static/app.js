// SICAS — arranque: inicio de sesión (contraseña -> cambio de clave -> MFA), menú por permisos y enrutador por hash.
(() => {
  'use strict';
  const S = window.SICAS, $ = (id) => document.getElementById(id);
  const views = ['login', 'change', 'enroll', 'mfa', 'app'];
  let challenge = null;

  const show = (name) => {
    views.forEach((v) => $('view-' + v).classList.toggle('hidden', v !== name));
    $('main').classList.toggle('wide', name === 'app');
    $('account-menu').classList.toggle('hidden', name !== 'app');
    $('btn-logout').classList.toggle('hidden', name !== 'app');
  };

  // ---------------------------------------------------------------- sesión
  async function api(path, body) {
    const r = await S.call(path, { method: 'POST', json: body || {} });
    return r;
  }
  function route(data) {
    challenge = data.challenge;
    if (data.status === 'PASSWORD_CHANGE_REQUIRED') show('change');
    else if (data.status === 'MFA_ENROLL_REQUIRED') { show('enroll'); startEnroll(); }
    else if (data.status === 'MFA_REQUIRED') { show('mfa'); $('mfa-code').focus(); }
  }
  async function startEnroll() {
    const r = await api('/auth/mfa/enroll', { challenge });
    if (!r.ok) { S.say('No fue posible iniciar la configuración. Vuelva a ingresar.'); show('login'); return; }
    challenge = r.data.challenge;
    $('mfa-secret').textContent = r.data.secret;
    $('mfa-uri').textContent = r.data.otpauth_uri;

    const qrImage = $('mfa-qr');
    qrImage.onerror = () => {
      qrImage.classList.add('hidden');
      $('mfa-manual-setup').open = true;
      S.say('No se pudo mostrar el QR. Use la alternativa manual.');
    };
    if (typeof r.data.qr_data_uri === 'string' &&
        r.data.qr_data_uri.startsWith('data:image/png;base64,')) {
      qrImage.src = r.data.qr_data_uri;
      qrImage.classList.remove('hidden');
    } else {
      qrImage.removeAttribute('src');
      qrImage.classList.add('hidden');
      $('mfa-manual-setup').open = true;
      S.say('No se pudo mostrar el QR. Puede usar la clave manual.');
    }
  }
  function enter(user) {
    S.user = user;
    S.perms = new Set(user.permissions || []);
    $('whoami').textContent = `${user.username} (${(user.roles || []).map(S.roleLabel).join(', ') || 'sin roles'})`;
    show('app'); S.say('');
    buildNav(); navigate();
    if (typeof S.refreshNotificationCount === 'function') {
      S.refreshNotificationCount();
      if (!S.notificationTimer) {
        S.notificationTimer = setInterval(() => S.refreshNotificationCount(), 60000);
        S.timers.push(S.notificationTimer);
      }
    }
  }
  async function guarded(btn, fn) {
    btn.disabled = true; S.say('');
    try { await fn(); } catch (e) { S.say('Error de comunicación con el servidor.'); } finally { btn.disabled = false; }
  }
  S.onSessionLost = () => {
    if (S.notificationTimer) { clearInterval(S.notificationTimer); S.notificationTimer = null; }
    if (typeof S.resetNotificationCountState === 'function') S.resetNotificationCountState();
    S.clearTimers(); S.perms = new Set(); S.user = null; show('login');
    S.say('Su sesión expiró. Ingrese de nuevo.');
  };

  $('btn-login').onclick = (e) => guarded(e.target, async () => {
    const r = await api('/auth/login', { username: $('username').value, password: $('password').value });
    if (!r.ok) return S.say(r.status === 429 ? 'Demasiados intentos. Espere un minuto.' : (r.data.error || 'No fue posible ingresar.'));
    $('password').value = ''; route(r.data);
  });
  $('btn-change').onclick = (e) => guarded(e.target, async () => {
    const r = await api('/auth/password/change', { challenge, old_password: $('old_password').value, new_password: $('new_password').value });
    if (!r.ok) return S.say(r.data.error || 'No fue posible cambiar la contraseña.');
    $('old_password').value = ''; $('new_password').value = ''; S.say('Contraseña actualizada.', true); route(r.data);
  });
  $('btn-confirm').onclick = (e) => guarded(e.target, async () => {
    const r = await api('/auth/mfa/confirm', { challenge, code: $('enroll-code').value });
    if (!r.ok) return S.say('Código incorrecto o vencido.');
    $('enroll-code').value = ''; enter(r.data.user);
  });
  $('btn-mfa').onclick = (e) => guarded(e.target, async () => {
    const r = await api('/auth/mfa/verify', { challenge, code: $('mfa-code').value });
    if (!r.ok) return S.say('Código incorrecto o cuenta no disponible.');
    $('mfa-code').value = ''; enter(r.data.user);
  });
  $('mfa-code').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('btn-mfa').click(); });
  $('password').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('btn-login').click(); });
  $('btn-logout').onclick = async () => {
    await api('/auth/logout');
    if (S.notificationTimer) { clearInterval(S.notificationTimer); S.notificationTimer = null; }
    if (typeof S.resetNotificationCountState === 'function') S.resetNotificationCountState();
    S.clearTimers(); S.perms = new Set(); S.user = null; location.hash = '';
    $('whoami').textContent = ''; $('page').replaceChildren(); show('login'); S.say('Sesión cerrada.', true);
  };

  // Panel desplegable de cuenta. El cierre de sesión conserva el flujo existente.
  const accountMenu = $('account-menu');
  const accountToggle = $('account-menu-toggle');
  const accountPanel = $('account-menu-panel');
  function closeAccountMenu() {
    accountPanel.classList.add('hidden');
    accountToggle.setAttribute('aria-expanded', 'false');
  }
  accountToggle.addEventListener('click', () => {
    const open = accountPanel.classList.contains('hidden');
    accountPanel.classList.toggle('hidden', !open);
    accountToggle.setAttribute('aria-expanded', String(open));
    if (open && typeof S.refreshNotificationCount === 'function') S.refreshNotificationCount();
  });
  document.addEventListener('click', (event) => {
    if (!accountMenu.contains(event.target)) closeAccountMenu();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeAccountMenu(); });
  // Navegación accesible del desplegable de cuenta con flechas, Inicio/Fin y Escape.
  const accountMenuItems = () => Array.from(accountPanel.querySelectorAll('[role="menuitem"]'))
    .filter((item) => !item.classList.contains('hidden') && !item.disabled && item.getAttribute('aria-hidden') !== 'true');
  accountToggle.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    if (accountPanel.classList.contains('hidden')) accountToggle.click();
    accountMenuItems()[0]?.focus();
  });
  accountPanel.addEventListener('keydown', (event) => {
    const items = accountMenuItems();
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAccountMenu();
      accountToggle.focus();
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !items.length) return;
    event.preventDefault();
    const current = items.indexOf(document.activeElement);
    let next = current < 0 ? 0 : current;
    if (event.key === 'ArrowDown') next = (next + 1) % items.length;
    if (event.key === 'ArrowUp') next = (next - 1 + items.length) % items.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = items.length - 1;
    items[next].focus();
  });
  $('btn-notifications').addEventListener('click', () => {
    closeAccountMenu(); if (S.openNotificationCenter) S.openNotificationCenter('all');
  });
  $('btn-settings').addEventListener('click', () => {
    closeAccountMenu();
    const user = S.user || {};
    const content = S.h('div', { class: 'account-settings-summary' },
      S.h('p', null, 'Configuración de la cuenta y seguridad.'),
      S.h('dl', null,
        S.h('dt', null, 'Usuario'), S.h('dd', null, user.username || '—'),
        S.h('dt', null, 'Roles'), S.h('dd', null, (user.roles || []).map(S.roleLabel).join(', ') || 'Sin roles asignados'),
        S.h('dt', null, 'Sesión'), S.h('dd', null, 'Autenticación multifactor (MFA) completada')) ,
      S.h('p', { class: 'muted' }, 'Los cambios de contraseña y la recuperación de MFA continúan sujetos a los flujos de seguridad existentes.'));
    const modal = S.modal('Configuración', content);
    modal.footer.append(S.h('button', { class: 'secondary', onclick: () => modal.close() }, 'Cerrar'));
  });

  // ---------------------------------------------------------------- menú y rutas
  // Existe un único módulo de Auditorías. Algunas versiones anteriores
  // registraban además páginas separadas para Sistemas/Financiera.
  // Si una de esas páginas antiguas sigue cargada, no debe aparecer como
  // un segundo botón en el menú.
  const legacyAuditPage = (p) => {
    if (!p || p.id === 'audits') return false;
    const id = String(p.id || '').toLowerCase();
    const title = typeof p.title === 'function' ? String(p.title() || '') : String(p.title || '');
    return (
      id === 'auditoria-sistemas' ||
      id === 'auditoria-financiera' ||
      id === 'audit-systems' ||
      id === 'audit-financial' ||
      id.includes('auditoria-sistemas') ||
      id.includes('auditoria-financiera') ||
      title === 'Auditoría de Sistemas' ||
      (title === 'Auditoría Financiera' || title === 'Auditoría Operativa')
    );
  };

  const allVisible = () => S.pages.filter((p) => !p.perms.length || S.can(...p.perms));

  const visible = () => {
    const pages = allVisible();
    const unifiedAudits = pages.some((p) => p.id === 'audits');
    if (!unifiedAudits) return pages;
    return pages.filter((p) => !legacyAuditPage(p));
  };

  const auditRouteAlias = (id) => {
    const pages = visible();
    if (!pages.some((p) => p.id === 'audits')) return id;
    const probe = { id };
    return legacyAuditPage(probe) ? 'audits' : id;
  };

  function pageTitle(p) {
    return typeof p.title === 'function' ? p.title() : p.title;
  }

  // SICAS-INTEGRATED-VISUAL-20261014-v2
  function shortNavName(label) {
    const words = String(label || '').trim().split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      return words.slice(0, 2)
        .map((word) => Array.from(word)[0])
        .join('')
        .toLocaleUpperCase('es');
    }
    return Array.from(words[0] || '')
      .slice(0, 2)
      .join('')
      .toLocaleUpperCase('es');
  }

  function classifyPage() {
    const root = $('page');
    const route = (
      location.hash.replace(/^#\/?/, '').split('/')[0] || ''
    ).trim().toLocaleLowerCase('es');

    const heading = (
      root.querySelector('h1, h2, h3')?.textContent || ''
    ).trim().toLocaleLowerCase('es');

    let view = 'general';

    // La ruta identifica el módulo incluso cuando el título es un código.
    if (route === 'audits') {
      view = 'audit';
    } else if (route === 'contralor-dashboard' || /contralor|dashboard ejecutivo|^dashboard$/.test(heading)) {
      view = 'contralor';
    } else if (/registro de actividad|actividad del auditor/.test(heading)) {
      view = 'activity';
    } else if (/c[eé]dula|suscripci[oó]n|reclamo|indemnizaci[oó]n/.test(heading)) {
      view = 'worksheet';
    } else if (/auditor[ií]a|expediente|trabajo de campo/.test(heading)) {
      view = 'audit';
    }

    root.dataset.sicasView = view;
  }

  function buildNav() {
    const nav = $('nav');
    const app = $('view-app');
    const collapsed = app.classList.contains('sicas-nav-collapsed');

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'sicas-nav-toggle';
    toggle.setAttribute('aria-controls', 'nav');
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.title = collapsed ? 'Expandir navegación' : 'Plegar navegación';
    toggle.textContent = collapsed ? '› Expandir menú' : '‹ Plegar menú';

    toggle.addEventListener('click', () => {
      const isCollapsed = app.classList.toggle('sicas-nav-collapsed');
      const label = isCollapsed ? '› Expandir menú' : '‹ Plegar menú';

      toggle.setAttribute('aria-expanded', String(!isCollapsed));
      toggle.title = isCollapsed ? 'Expandir navegación' : 'Plegar navegación';

      if (toggle.textContent !== label) {
        toggle.textContent = label;
      }
    });

    const buttons = visible().filter((p) => !p.hiddenFromNav).map((p) => {
      const label = String(pageTitle(p) || '').trim();
      const button = document.createElement('button');

      button.type = 'button';
      button.id = 'nav-' + p.id;
      button.dataset.sicasNavItem = 'true';
      button.dataset.sicasShort = shortNavName(label);
      button.setAttribute('aria-label', label);
      button.title = label;

      const labelElement = document.createElement('span');
      labelElement.className = 'sicas-nav-label';
      labelElement.textContent = label;
      button.appendChild(labelElement);

      button.addEventListener('click', () => {
        location.hash = '#/' + p.id;
      });

      return button;
    });

    nav.replaceChildren(toggle, ...buttons);
  }
  let navigationToken = 0;
  S.isNavigationCurrent = (token) => Boolean(S.user) && token === navigationToken;
  async function navigate() {
    if (!S.user) return;
    const currentNavigation = ++navigationToken;
    if (S.onLeave) { S.onLeave(); S.onLeave = null; }

    let [id, ...args] = (location.hash.replace(/^#\/?/, '') || 'home').split('/');
    id = auditRouteAlias(id);

    const pages = visible();
    const page = pages.find((p) => p.id === id) || pages[0];
    if (!page) return;

    // Si alguien entra por una ruta antigua, la normalizamos al módulo único.
    if (id === 'audits' && location.hash.split('/')[1] && legacyAuditPage({ id: location.hash.split('/')[1] })) {
      const raw = location.hash.replace(/^#\/?/, '').split('/');
      raw[0] = 'audits';
      location.hash = '#/' + raw.join('/');
      return;
    }

    document.querySelectorAll('#nav button').forEach((b) =>
      b.classList.toggle('active', b.id === 'nav-' + page.id)
    );

    const el = $('page');
    el.replaceChildren(S.h('p', { class: 'muted' }, 'Cargando…'));
    const holder = S.h('div');

    try {
      await page.render(holder, args, currentNavigation);
      if (currentNavigation !== navigationToken) return;
      el.replaceChildren(holder);
      classifyPage();
    } catch (e) {
      if (currentNavigation !== navigationToken) return;
      console.error(e);
      el.replaceChildren(
        S.h('div', { class: 'warn' }, 'No se pudo mostrar esta pantalla: ' + e.message)
      );
    }
  }
  window.addEventListener('hashchange', navigate);

  // Si ya hay sesión (cookie vigente), entrar directo
  (async () => {
    let r = await S.call('/auth/me');
    if (!r.ok && await S.tryRefresh()) r = await S.call('/auth/me');
    if (r.ok) enter({ username: r.data.username, roles: r.data.roles, permissions: r.data.permissions });
  })();
})();
