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
  function whoami(user) {
    const acting = (user.delegations || []).map((d) => `suplente de ${d.titular} (${d.stage}) hasta ${d.ends_on}`);
    $('whoami').textContent = `${user.username} (${(user.roles || []).map(S.roleLabel).join(', ') || 'sin roles'})` +
      (acting.length ? ' · ' + acting.join(' · ') : '');
  }
  function enter(user) {
    S.user = user;
    S.perms = new Set(user.permissions || []);
    whoami(user);
    show('app'); S.say('');
    buildNav(); navigate();
    if (S.startScheduleWatch) S.startScheduleWatch();       // aviso 15 minutos antes del cierre y bloqueo fuera de horario
    // Las suplencias vigentes agregan permisos de una etapa del flujo; /auth/me los incluye.
    if (!user.delegations) {
      S.call('/auth/me').then((r) => {
        if (!r.ok || S.user !== user) return;
        user.delegations = r.data.delegations || [];
        whoami(user);
        const extra = (r.data.permissions || []).filter((p) => !S.perms.has(p));
        if (extra.length) { extra.forEach((p) => S.perms.add(p)); buildNav(); }
      }).catch(() => {});
    }
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

  // Menú lateral agrupado por secciones: con muchos módulos (Contralor, jefes) la lista plana se veía recargada.
  const NAV_GROUPS = [
    ['principal', 'Principal', ['home', 'contralor-dashboard', 'general-reports']],
    ['auditoria', 'Auditoría', ['audits', 'ti-branches', 'applications', 'findings', 'lcft', 'reports', 'ingestion']],
    ['gestion', 'Gestión', ['roles', 'overtime', 'auditor-activity', 'work-schedule']],
    ['config', 'Configuración', ['engine', 'users', 'rules-admin', 'system', 'admin-monitor', 'access-review', 'annulments']],
  ];
  const NAV_ICON_PATHS = {
    home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
    'contralor-dashboard': 'M4 20V10M10 20V4M16 20v-7M22 20H2',
    'general-reports': 'M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h8',
    audits: 'M9 3h6v3H9zM6 5h3M15 5h3v16H6V5M9 12l2 2 4-4',
    'ti-branches': 'M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6',
    applications: 'M3 4h18v12H3zM8 20h8M12 16v4',
    findings: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5',
    lcft: 'M12 2l8 4v6c0 5-4 9-8 10-4-1-8-5-8-10V6z',
    reports: 'M6 2h12v20H6zM9 7h6M9 11h6M9 15h4',
    ingestion: 'M12 3v12M7 10l5 5 5-5M4 21h16',
    roles: 'M4 4h16v12H8l-4 4zM8 9h8M8 12h5',
    overtime: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 3',
    'auditor-activity': 'M3 12h4l3-8 4 16 3-8h4',
    'work-schedule': 'M3 5h18v16H3zM3 10h18M8 3v4M16 3v4',
    engine: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2',
    users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21c0-4 3-6 7-6s7 2 7 6M17 11a3 3 0 1 0 0-6M22 20c0-3-2-5-5-5',
    'rules-admin': 'M4 6h16M4 12h10M4 18h6M17 15l2 2 3-4',
    system: 'M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01',
    'admin-monitor': 'M3 4h18v13H3zM8 21h8M6 12l3-3 3 3 4-4',
    'access-review': 'M8 11V7a4 4 0 1 1 8 0v4M5 11h14v10H5zM12 15v2',
    annulments: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM6 6l12 12',
  };
  const NAV_FOLD_KEY = 'sicas.nav.folded';
  function navFolded() {
    try { return JSON.parse(localStorage.getItem(NAV_FOLD_KEY) || '[]'); } catch { return []; }
  }
  function saveNavFolded(list) {
    try { localStorage.setItem(NAV_FOLD_KEY, JSON.stringify(list)); } catch { /* sin almacenamiento */ }
  }
  function navIcon(id) {
    const d = NAV_ICON_PATHS[id];
    if (!d) return null;
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('sicas-nav-icon');
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
    return svg;
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

    // En pantallas pequeñas el menú es un desplegable: un solo botón con la página actual.
    const mobile = document.createElement('button');
    mobile.type = 'button';
    mobile.className = 'sicas-nav-mobile';
    mobile.setAttribute('aria-expanded', 'false');
    mobile.innerHTML = '<span class="sicas-nav-burger" aria-hidden="true"></span><span class="sicas-nav-mobile-label">Menú</span><span class="sicas-nav-chevron" aria-hidden="true"></span>';
    mobile.addEventListener('click', () => {
      const open = nav.classList.toggle('sicas-nav-open');
      mobile.setAttribute('aria-expanded', String(open));
    });

    const pages = visible().filter((p) => !p.hiddenFromNav);
    const makeButton = (p) => {
      const label = String(pageTitle(p) || '').trim();
      const button = document.createElement('button');

      button.type = 'button';
      button.id = 'nav-' + p.id;
      button.dataset.sicasNavItem = 'true';
      button.dataset.sicasShort = shortNavName(label);
      button.setAttribute('aria-label', label);
      button.title = label;

      const icon = navIcon(p.id);
      if (icon) {
        button.appendChild(icon);
        button.classList.add('has-icon');
      }
      const labelElement = document.createElement('span');
      labelElement.className = 'sicas-nav-label';
      labelElement.textContent = label;
      button.appendChild(labelElement);

      button.addEventListener('click', () => {
        nav.classList.remove('sicas-nav-open');
        mobile.setAttribute('aria-expanded', 'false');
        location.hash = '#/' + p.id;
      });

      return button;
    };

    const known = new Set(NAV_GROUPS.flatMap((g) => g[2]));
    const groups = NAV_GROUPS.map(([key, label, ids]) => [key, label, ids.map((id) => pages.find((p) => p.id === id)).filter(Boolean)]);
    const others = pages.filter((p) => !known.has(p.id));
    if (others.length) groups.push(['otros', 'Otros', others]);

    const folded = navFolded();
    const sections = groups.filter((g) => g[2].length).map(([key, label, items]) => {
      const section = document.createElement('div');
      section.className = 'sicas-nav-group';
      section.dataset.group = key;
      if (folded.includes(key)) section.classList.add('folded');

      const head = document.createElement('button');
      head.type = 'button';
      head.className = 'sicas-nav-group-head';
      head.setAttribute('aria-expanded', String(!folded.includes(key)));
      head.innerHTML = '<span></span><span class="sicas-nav-chevron" aria-hidden="true"></span>';
      head.firstChild.textContent = label;
      head.addEventListener('click', () => {
        const isFolded = section.classList.toggle('folded');
        head.setAttribute('aria-expanded', String(!isFolded));
        const list = navFolded().filter((k) => k !== key);
        if (isFolded) list.push(key);
        saveNavFolded(list);
      });

      const list = document.createElement('div');
      list.className = 'sicas-nav-items';
      list.append(...items.map(makeButton));
      section.append(head, list);
      return section;
    });

    nav.replaceChildren(toggle, mobile, ...sections);
  }

  // Marca la página activa, abre su sección y rotula el desplegable móvil.
  function syncNav(page) {
    document.querySelectorAll('#nav [data-sicas-nav-item]').forEach((b) => {
      const on = b.id === 'nav-' + page.id;
      b.classList.toggle('active', on);
      if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    const active = document.getElementById('nav-' + page.id);
    const section = active && active.closest('.sicas-nav-group');
    if (section && section.classList.contains('folded')) {
      section.classList.remove('folded');
      section.querySelector('.sicas-nav-group-head')?.setAttribute('aria-expanded', 'true');
    }
    const label = document.querySelector('#nav .sicas-nav-mobile-label');
    if (label) label.textContent = active ? active.getAttribute('aria-label') : 'Menú';
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

    syncNav(page);

    const el = $('page');
    // El título puede ser un texto o una función (Auditorías cambia según el dominio): solo se usa si es texto.
    const pageTitle = typeof page.title === 'string' ? page.title.toLowerCase() : '';
    el.replaceChildren(S.loading(pageTitle ? `Cargando ${pageTitle}…` : 'Cargando…'));
    const holder = S.h('div', { class: 'sicas-page-enter' });

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
    if (r.ok) enter({ username: r.data.username, roles: r.data.roles, permissions: r.data.permissions, delegations: r.data.delegations || [] });
  })();
})();
