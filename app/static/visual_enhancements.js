/* SICAS-VISUAL-NAV-20261013-v1 */
(() => {
  'use strict';

  const start = () => {
    const app = document.getElementById('view-app');
    const nav = document.getElementById('nav');
    const page = document.getElementById('page');

    if (!app || !nav || !page) return;

    function shortName(label) {
      const words = label.trim().split(/\s+/).filter(Boolean);
      if (words.length > 1) {
        return words.slice(0, 2).map((word) => Array.from(word)[0]).join('').toUpperCase();
      }
      return Array.from(label).slice(0, 2).join('').toUpperCase();
    }

    function updateToggle(toggle) {
      const collapsed = app.classList.contains('sicas-nav-collapsed');
      toggle.setAttribute('aria-expanded', String(!collapsed));
      const nextToggleLabel = collapsed ? '› Expandir menú' : '‹ Plegar menú';
      if (toggle.textContent !== nextToggleLabel) {
        toggle.textContent = nextToggleLabel;
      }
      toggle.title = collapsed ? 'Expandir navegación' : 'Plegar navegación';
    }

    function enhanceNavigation() {
      let toggle = nav.querySelector(':scope > .sicas-nav-toggle');

      if (!toggle) {
        toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'sicas-nav-toggle';
        toggle.setAttribute('aria-controls', 'nav');
        toggle.addEventListener('click', () => {
          app.classList.toggle('sicas-nav-collapsed');
          updateToggle(toggle);
        });
        nav.insertBefore(toggle, nav.firstChild);
      }

      updateToggle(toggle);

      nav.querySelectorAll('button, a, [role="button"]').forEach((item) => {
        if (item === toggle || item.dataset.sicasNavEnhanced === 'true') return;

        const label = (item.getAttribute('aria-label') || item.textContent || '').trim();
        if (!label) return;

        item.dataset.sicasNavEnhanced = 'true';
        item.dataset.sicasNavItem = 'true';
        item.dataset.sicasShort = shortName(label);
        item.title = item.title || label;
        if (!item.hasAttribute('aria-label')) item.setAttribute('aria-label', label);

        const walk = (parent) => {
          Array.from(parent.childNodes).forEach((node) => {
            if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
              const span = document.createElement('span');
              span.className = 'sicas-nav-label';
              span.textContent = node.textContent.trim();
              node.replaceWith(span);
            } else if (node.nodeType === Node.ELEMENT_NODE &&
                       node.namespaceURI !== 'http://www.w3.org/2000/svg' &&
                       !node.classList.contains('sicas-nav-label') &&
                       !['SCRIPT', 'STYLE'].includes(node.tagName)) {
              walk(node);
            }
          });
        };

        walk(item);
      });
    }

    function classifyPage() {
      const heading = (page.querySelector('h1, h2, h3')?.textContent || '').trim().toLocaleLowerCase('es');
      let view = 'general';

      if (/contralor|dashboard ejecutivo/.test(heading)) {
        view = 'contralor';
      } else if (/registro de actividad|actividad del auditor/.test(heading)) {
        view = 'activity';
      } else if (/c[eé]dula|suscripci[oó]n|reclamo|indemnizaci[oó]n/.test(heading)) {
        view = 'worksheet';
      } else if (/auditor[ií]a|expediente|trabajo de campo/.test(heading)) {
        view = 'audit';
      }

      page.dataset.sicasView = view;
    }

    enhanceNavigation();
    classifyPage();

    // Los módulos SPA pueden reemplazar el contenido de #page o los elementos de #nav.
    const observer = new MutationObserver(() => {
      enhanceNavigation();
      classifyPage();
    });

    observer.observe(app, { childList: true, subtree: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
