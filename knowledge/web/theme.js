// Apply before the stylesheet loads so a saved dark theme never flashes light.
(() => {
  'use strict';
  const key = 'figuring-out.theme.v1';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = null;
  const valid = value => value === 'dark' || value === 'light';
  try { const saved = localStorage.getItem(key); if (valid(saved)) preference = saved; } catch {}
  function apply() {
    const dark = (preference || (system.matches ? 'dark' : 'light')) === 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#151b17' : '#fafbf8');
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    }
  }
  apply();
  system.addEventListener('change', () => { if (!preference) apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      preference = valid(event.newValue) ? event.newValue : null;
      apply();
    }
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, preference); } catch {}
      apply();
    });
  });
})();
