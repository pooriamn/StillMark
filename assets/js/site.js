/*
  Behaviour for the redesigned pages. Pages are fully rendered at build time;
  this only adds the menu, the header state and the full-screen viewer.
  It loads no site data.
*/

function initHeader() {
  const header = document.querySelector('[data-site-header]');
  if (!header) return;
  const update = () => header.toggleAttribute('data-scrolled', window.scrollY > 8);
  update();
  window.addEventListener('scroll', update, { passive: true });
}

function initMenu() {
  const button = document.querySelector('[data-menu-button]');
  const nav = document.getElementById(button?.getAttribute('aria-controls') || '');
  if (!button || !nav) return;

  const setOpen = (open) => {
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? 'Close' : 'Menu';
    nav.toggleAttribute('data-open', open);
    document.body.toggleAttribute('data-menu-open', open);
  };

  button.addEventListener('click', () => setOpen(button.getAttribute('aria-expanded') !== 'true'));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      button.focus();
    }
  });
  window.matchMedia('(min-width: 52.01rem)').addEventListener('change', (event) => {
    if (event.matches) setOpen(false);
  });
}

function initViewer() {
  const viewer = document.querySelector('[data-viewer]');
  if (!viewer || typeof viewer.showModal !== 'function') return;
  const image = viewer.querySelector('img');
  const close = viewer.querySelector('[data-viewer-close]');

  document.querySelectorAll('[data-viewer-open]').forEach((trigger) => {
    trigger.addEventListener('click', () => {
      const source = trigger.querySelector('img');
      image.src = trigger.dataset.viewerSrc || source?.currentSrc || source?.src || '';
      image.alt = source?.alt || '';
      viewer.showModal();
    });
  });

  close?.addEventListener('click', () => viewer.close());
  viewer.addEventListener('click', (event) => {
    if (event.target === viewer) viewer.close();
  });

  // Arrow keys move to the previous or next photograph in the series.
  document.addEventListener('keydown', (event) => {
    if (event.target.closest('input, textarea, select')) return;
    const rel = event.key === 'ArrowLeft' ? 'prev' : event.key === 'ArrowRight' ? 'next' : '';
    const link = rel && document.querySelector(`.pager a[rel="${rel}"]`);
    if (link) window.location.href = link.href;
  });
}

initHeader();
initMenu();
initViewer();
