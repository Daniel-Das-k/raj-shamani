'use strict';
// Preserve only an application route, never a question or an external URL.
(() => {
  const route = new URLSearchParams(location.search).get('next') || '/' + location.hash;
  const safe = !/\s/.test(route) && /^\/(?:#(?:discover|conversations|saved(?:\/history)?|answer(?:\/[a-f0-9]{32})?))?$/.test(route) ? route : '/';
  document.querySelector('#sign-in-link').href = '/auth/login?next=' + encodeURIComponent(safe);
})();
