// SICAS — registro ligero y carga bajo demanda de módulos.
(() => {
  'use strict';

  const S = window.SICAS;
  if (!S || !Array.isArray(S.pages)) {
    throw new Error('El registro central de páginas de SICAS no está disponible.');
  }

  const currentAuditTitle = () => {
    const systems = S.can(
      'audit:systems_read',
      'audit:systems_execute',
      'audit:systems_review'
    );
    const financial = S.can(
      'audit:financial_read',
      'audit:financial_execute',
      'audit:financial_review'
    );

    if (systems && !financial) return 'Auditoría de Sistemas';
    if (financial && !systems) return 'Auditoría Operativa';
    return 'Auditorías';
  };

  const modules = {
    ops: {
      src: '/static/pages_ops.js?v=20261028-ie1',
      pages: [
        { id: 'ingestion', title: 'Cargas', perms: ['ingestion:read'] },
        { id: 'findings', title: 'Hallazgos', perms: ['finding:read'] },
        { id: 'lcft', title: 'LC/FT', perms: ['lcft:alert_read'] },
        {
          id: 'reports',
          title: 'Dictámenes',
          perms: ['report:read', 'report:read_approved']
        }
      ]
    },

    audit: {
      src: '/static/pages_audit.js?v=20261028-ie1',
      pages: [
        {
          id: 'audits',
          title: currentAuditTitle,
          perms: [
            'audit:read',
            'audit:read_final',
            'audit:sign_gerente',
            'audit:financial_read',
            'audit:systems_read'
          ]
        }
      ]
    },

    contralor: {
      src: '/static/pages_contralor.js?v=20261028-ie1',
      pages: [
        {
          id: 'contralor-dashboard',
          title: 'Dashboard',
          perms: [
            'dashboard:contralor',
            'dashboard:executive',
            'audit:financial_review',
            'audit:systems_review'
          ]
        }
      ]
    },

    activity: {
      src: '/static/pages_activity.js?v=20261014-full2',
      pages: [
        {
          id: 'auditor-activity',
          title: 'Registro de actividad',
          perms: ['audit:manage']
        }
      ]
    }
  };

  const placeholders = new Map();
  const moduleByPage = new Map();
  const loadPromises = new Map();

  function registerPlaceholders() {
    for (const [moduleName, descriptor] of Object.entries(modules)) {
      for (const meta of descriptor.pages) {
        if (
          S.pages.some((page) => page.id === meta.id) ||
          placeholders.has(meta.id)
        ) {
          throw new Error(
            `El identificador de página "${meta.id}" ya está registrado.`
          );
        }

        const placeholder = {
          id: meta.id,
          title: meta.title,
          perms: [...meta.perms],
          render: async (el, args, navigationId) => {
            await loadModule(moduleName);

            if (
              Number.isInteger(navigationId) &&
              typeof S.isNavigationCurrent === 'function' &&
              !S.isNavigationCurrent(navigationId)
            ) return;

            const actual = S.pages.find(
              (page) => page.id === meta.id && page !== placeholder
            );

            if (!actual || actual.__sicasLazyPlaceholder) {
              throw new Error(
                `El módulo no registró correctamente la página "${meta.id}".`
              );
            }

            return actual.render(el, args || []);
          }
        };

        Object.defineProperty(placeholder, '__sicasLazyPlaceholder', {
          value: moduleName
        });

        placeholders.set(meta.id, placeholder);
        moduleByPage.set(meta.id, moduleName);
        S.pages.push(placeholder);
      }
    }
  }

  function activateModule(moduleName) {
    const descriptor = modules[moduleName];
    const replacements = new Map();
    const actualPages = new Set();

    for (const meta of descriptor.pages) {
      const placeholder = placeholders.get(meta.id);
      const actual = S.pages.find(
        (page) => page.id === meta.id && page !== placeholder
      );

      if (!actual) {
        throw new Error(
          `El módulo "${moduleName}" no registró la página "${meta.id}".`
        );
      }

      const actualPerms = Array.isArray(actual.perms) ? actual.perms : [];
      if (JSON.stringify(actualPerms) !== JSON.stringify(meta.perms)) {
        throw new Error(
          `Los permisos declarados para "${meta.id}" no coinciden con el módulo.`
        );
      }

      replacements.set(placeholder, actual);
      actualPages.add(actual);
    }

    // Sustituye los marcadores por las páginas reales en sus posiciones
    // originales y quita las referencias duplicadas agregadas por el módulo.
    const nextPages = [];
    const seen = new Set();

    for (const current of S.pages) {
      if (actualPages.has(current) && seen.has(current)) continue;

      const page = replacements.get(current) || current;
      if (seen.has(page)) continue;

      seen.add(page);
      nextPages.push(page);
    }

    S.pages.splice(0, S.pages.length, ...nextPages);
  }

  function loadModule(moduleName) {
    if (loadPromises.has(moduleName)) {
      return loadPromises.get(moduleName);
    }

    const descriptor = modules[moduleName];
    if (!descriptor) {
      return Promise.reject(new Error('Módulo SICAS desconocido.'));
    }

    const script = document.createElement('script');
    script.src = descriptor.src;
    script.async = true;
    script.dataset.sicasLazyModule = moduleName;

    const promise = new Promise((resolve, reject) => {
      script.addEventListener('load', () => {
        try {
          activateModule(moduleName);
          resolve();
        } catch (error) {
          const failedPageIds = new Set(
            descriptor.pages.map((meta) => meta.id)
          );
          S.pages.splice(
            0,
            S.pages.length,
            ...S.pages.filter((page) =>
              !failedPageIds.has(page.id) ||
              placeholders.get(page.id) === page
            )
          );
          script.remove();
          loadPromises.delete(moduleName);
          reject(error);
        }
      }, { once: true });

      script.addEventListener('error', () => {
        script.remove();
        loadPromises.delete(moduleName);
        reject(
          new Error(`No fue posible cargar el módulo "${moduleName}".`)
        );
      }, { once: true });

      document.head.appendChild(script);
    });

    loadPromises.set(moduleName, promise);
    return promise;
  }

  registerPlaceholders();
})();
