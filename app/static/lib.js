// SICAS — utilidades de interfaz. Todo el texto dinámico se inserta con textContent (nunca innerHTML).
(() => {
  'use strict';
  const S = window.SICAS = { perms: new Set(), user: null, timers: [] };

  S.can = (...p) => p.some((x) => S.perms.has(x));

  S.h = (tag, props, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === false || v == null) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  };
  const h = S.h;

  const LABELS = {
    CRITICAL: 'Crítica', HIGH: 'Alta', MEDIUM: 'Media', LOW: 'Baja',
    OPEN: 'Abierto', IN_REVIEW: 'En revisión', ESCALATED: 'Escalado', CLOSED_FP: 'Cerrado (falso positivo)', CLOSED_RESOLVED: 'Cerrado (resuelto)',
    DRAFT: 'Borrador', SUBMITTED: 'Enviado', RETURNED: 'Devuelto', APPROVED: 'Aprobado', SIGNED: 'Firmado',
    QUEUED: 'En cola', PROCESSING: 'Procesando', COMPLETED: 'Completada', FAILED: 'Fallida', CANCELLED: 'Cancelada',
    PENDING: 'Pendiente', REJECTED: 'Rechazada', RUNNING: 'En curso', OK: 'OK', SUCCESS: 'Éxito', FAILURE: 'Fallo', DENIED: 'Denegado',
    ACTIVE: 'Activo', INACTIVE: 'Inactivo', GRANT: 'Otorgar', REVOKE: 'Retirar',
  };
  S.label = (v) => LABELS[v] || v;
  S.badge = (v) => h('span', { class: 'badge ' + v }, S.label(v));
  S.fmt = (v) => (v ? new Date(v).toLocaleString('es-VE') : '');

  S.say = (text, ok = false) => {
    const m = document.getElementById('msg');
    m.textContent = text || '';
    m.className = ok ? 'ok' : '';
    if (text) setTimeout(() => { if (m.textContent === text) m.textContent = ''; }, ok ? 5000 : 12000);
  };

  S.clearTimers = () => { S.timers.forEach(clearInterval); S.timers = []; };

  // ---------------------------------------------------------------- API
  const cookie = (name) => (document.cookie.split('; ').find((c) => c.startsWith(name + '=')) || '').split('=')[1] || '';

  async function raw(path, { method = 'GET', json, form } = {}) {
    const headers = {};
    let body;
    if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
    if (form) body = form;
    if (method !== 'GET') headers['X-CSRF-TOKEN'] = cookie('csrf_access_token');
    const res = await fetch('/api/v1' + path, { method, headers, body, credentials: 'same-origin' });
    const type = res.headers.get('Content-Type') || '';
    let data = {};
    let blob = null;
    if (type.includes('application/json')) { try { data = await res.json(); } catch (_) { /* vacío */ } }
    else if (res.ok) blob = await res.blob();
    return { ok: res.ok, status: res.status, data, blob, res };
  }

  async function tryRefresh() {
    const res = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-TOKEN': cookie('csrf_refresh_token') } });
    return res.ok;
  }

  S.tryRefresh = tryRefresh;
  S.askStepUp = () => new Promise((resolve) => {
    const input = h('input', { inputmode: 'numeric', maxlength: '6', autocomplete: 'one-time-code' });
    const m = S.modal('Confirme su identidad', h('div', null,
      h('p', null, 'Esta acción requiere verificación reciente. Escriba el código de 6 dígitos de su aplicación autenticadora.'),
      h('label', null, 'Código', input)));
    const done = (v) => { m.close(); resolve(v); };
    m.footer.append(h('button', { class: 'secondary', onclick: () => done(false) }, 'Cancelar'),
      h('button', { onclick: async (e) => {
        e.target.disabled = true;
        const r = await raw('/auth/step-up', { method: 'POST', json: { code: input.value } });
        if (r.ok) done(true); else { S.say(r.data.error || 'Código incorrecto'); e.target.disabled = false; }
      } }, 'Confirmar'));
    input.focus();
  });

  S.call = async (path, opts) => {
    let r = await raw(path, opts);
    if (r.status === 401 && r.data.step_up_required) {
      if (await S.askStepUp()) r = await raw(path, opts);
    } else if (r.status === 401 && !path.startsWith('/auth/')) {
      if (await tryRefresh()) r = await raw(path, opts);
      else { S.onSessionLost && S.onSessionLost(); }
    }
    return r;
  };
  S.err = (r) => r.data.error || r.data.msg || ('Error ' + r.status);
  S.pages = [];

  // GET/POST que devuelve los datos o null (mostrando el error)
  S.get = async (path) => { const r = await S.call(path); if (!r.ok) { S.say(S.err(r)); return null; } return r.data; };
  S.send = async (path, method, json) => { const r = await S.call(path, { method, json }); if (!r.ok) { S.say(S.err(r)); return null; } return r.data; };

  // Abre un PDF/archivo en una pestaña nueva (la ventana se abre en el clic para que no la bloquee el navegador)
  S.openFile = async (path, filename, inline = true) => {
    const w = inline ? window.open('', '_blank') : null;
    const r = await S.call(path);
    if (!r.ok || !r.blob) { if (w) w.close(); S.say(S.err(r)); return; }
    if (w) { w.location = URL.createObjectURL(r.blob); } else S.download(r.blob, filename);
  };

  S.upload = async (path, formData) => {
    const r = await S.call(path, { method: 'POST', form: formData });
    return r;
  };

  S.stat = (n, l) => h('div', { class: 'card stat' }, h('div', { class: 'n' }, n), h('div', { class: 'l' }, l));
  S.score = (v) => (v == null ? '—' : Number(v).toFixed(1));
  S.ratingBadge = (r) => h(
  'span',
  { class: 'badge R_' + r },
  ({
    EXCELENTE: 'Excelente',
    SATISFACTORIO: 'Satisfactorio',
    ACEPTABLE: 'Aceptable',
    NECESITA_MEJORAS: 'Necesita mejoras',
    NO_SATISFACTORIA: 'No satisfactoria',
    SIN_CALIFICAR: 'Sin calificar'
  })[r] || r);
  S.date = (v) => (v ? String(v).slice(0, 10) : '');

  // ---------------------------------------------------------------- UI
  S.modal = (title, body) => {
    const footer = h('div', { class: 'row end' });
    const overlay = h('div', { class: 'overlay' }, h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, h('h3', null, title), body, footer));
    document.body.append(overlay);
    return { close: () => overlay.remove(), footer, overlay };
  };

  // fields: [{name,label,type:'text'|'textarea'|'select'|'checkbox'|'email'|'file',options:[[value,label]],required,value,hint}]
  S.ask = (title, fields, submitLabel = 'Aceptar', intro) => new Promise((resolve) => {
    const inputs = {};
    const form = h('div', null, intro ? h('p', { class: 'muted' }, intro) : null);
    for (const f of fields) {
      let el;
      if (f.type === 'textarea') el = h('textarea', { value: f.value || '' });
      else if (f.type === 'select') el = h('select', null, (f.options || []).map(([v, l]) => h('option', { value: v, selected: v === f.value }, l)));
      else if (f.type === 'checkbox') el = h('input', { type: 'checkbox', checked: !!f.value });
      else el = h('input', { type: f.type || 'text', value: f.value || '' });
      inputs[f.name] = el;
      form.append(f.type === 'checkbox'
        ? h('label', null, el, ' ', f.label)
        : h('label', null, f.label, el, f.hint ? h('span', { class: 'muted' }, f.hint) : null));
    }
    const m = S.modal(title, form);
    const done = (v) => { m.close(); resolve(v); };
    m.footer.append(h('button', { class: 'secondary', onclick: () => done(null) }, 'Cancelar'),
      h('button', { onclick: () => {
        const out = {};
        for (const f of fields) {
          const el = inputs[f.name];
          out[f.name] = f.type === 'checkbox' ? el.checked : f.type === 'file' ? (el.files[0] || null) : el.value.trim();
          if (f.required && !out[f.name]) { S.say('Complete el campo: ' + f.label); return; }
        }
        done(out);
      } }, submitLabel));
    const first = form.querySelector('input,textarea,select');
    if (first) first.focus();
  });

  S.tbl = (headers, rows, onRow) => {
    if (!rows.length) return h('div', { class: 'empty panel' }, 'Sin registros');
    return h('div', { class: 'tablewrap' }, h('table', null,
      h('thead', null, h('tr', null, headers.map((x) => h('th', null, x)))),
      h('tbody', null, rows.map((r, i) => h('tr', onRow ? { class: 'clickable', onclick: () => onRow(i) } : null, r.map((c) => h('td', null, c)))))));
  };

  S.busy = async (btn, fn) => {
    btn.disabled = true;
    try { await fn(); } catch (e) { S.say('Error inesperado: ' + e.message); } finally { btn.disabled = false; }
  };

  S.json = (obj) => h('pre', null, JSON.stringify(obj, null, 2));

  S.download = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: filename });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
})();
