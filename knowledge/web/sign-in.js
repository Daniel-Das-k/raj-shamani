'use strict';
// Preserve only an application route, never a question or an external URL.
(() => {
  const route = new URLSearchParams(location.search).get('next') || '/' + location.hash;
  const safe = !/\s/.test(route) && /^\/(?:#(?:discover|conversations|saved(?:\/history)?|answer(?:\/[a-f0-9]{32})?))?$/.test(route) ? route : '/';
  const link = document.querySelector('#sign-in-link');
  const switchLink = document.querySelector('#auth-switch-link');
  const progress = document.querySelector('#auth-progress');
  link.href = '/auth/login?next=' + encodeURIComponent(safe);
  const switchTarget = new URL(switchLink.getAttribute('href'), location.origin);
  switchTarget.searchParams.set('next', safe);
  switchLink.href = switchTarget.pathname + switchTarget.search;
  link.addEventListener('click', event => {
    if (link.getAttribute('aria-disabled') === 'true') { event.preventDefault(); return; }
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    link.setAttribute('aria-disabled', 'true');
    progress.textContent = document.documentElement.dataset.provider === 'google' ? 'Opening Google sign-in…' : 'Opening sign-in…';
  });
  window.addEventListener('pageshow', () => { link.removeAttribute('aria-disabled'); progress.textContent = ''; });
})();
