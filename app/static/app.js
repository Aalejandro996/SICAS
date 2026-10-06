// SICAS — arranque: inicio de sesión (contraseña -> cambio de clave -> MFA), menú por permisos y enrutador por hash.
(() => {
  'use strict';
  const S = window.SICAS, $ = (id) => document.getElementById(id);
  const views = ['login', 'change', 'enroll', 'mfa', 'app'];
  let challenge = null;

  const show = (name) => {
    views.forEach((v) => $('view-' + v).classList.toggle('hidden', v !== name));
    $('main').classList.toggle('wide', name === 'app');
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
  }
  function enter(user) {
    S.user = user;
    S.perms = new Set(user.permissions || []);
    $('whoami').textContent = `${user.username} (${(user.roles || []).join(', ') || 'sin roles'})`;
    show('app'); S.say('');
    buildNav(); navigate();
  }
  async function guarded(btn, fn) {
    btn.disabled = true; S.say('');
    try { await fn(); } catch (e) { S.say('Error de comunicación con el servidor.'); } finally { btn.disabled = false; }
  }
  S.onSessionLost = () => { S.perms = new Set(); show('login'); S.say('Su sesión expiró. Ingrese de nuevo.'); };

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
    await api('/auth/logout'); S.clearTimers(); S.perms = new Set(); location.hash = '';
    $('whoami').textContent = ''; $('page').replaceChildren(); show('login'); S.say('Sesión cerrada.', true);
  };

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
      title === 'Auditoría Financiera'
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

  function buildNav() {
    const nav = $('nav');
    nav.replaceChildren(...visible().map((p) =>
      S.h(
        'button',
        {
          id: 'nav-' + p.id,
          onclick: () => { location.hash = '#/' + p.id; }
        },
        pageTitle(p)
      )
    ));
  }

  async function navigate() {
    if (!S.user) return;
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
      await page.render(holder, args);
      el.replaceChildren(holder);
    } catch (e) {
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
