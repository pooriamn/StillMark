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

const PAGE_SIZE = 30;

function initPortfolio() {
  const filters = document.querySelector('[data-filters]');
  const items = [...document.querySelectorAll('[data-mosaic] > li')];
  if (!filters || !items.length) return;
  const more = document.querySelector('[data-more]');
  const status = document.querySelector('[data-filter-status]');
  const buttons = [...filters.querySelectorAll('[data-filter]')];
  let active = 'all';
  let limit = PAGE_SIZE;

  const render = () => {
    const matching = items.filter((item) => active === 'all' || item.dataset.series === active);
    items.forEach((item) => { item.hidden = true; });
    matching.slice(0, limit).forEach((item) => { item.hidden = false; });
    if (more) more.hidden = matching.length <= limit;
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.filter === active)));
    if (status) status.textContent = `Showing ${Math.min(limit, matching.length)} of ${matching.length} photographs`;
  };

  const select = (slug, { updateUrl = true } = {}) => {
    active = buttons.some((button) => button.dataset.filter === slug) ? slug : 'all';
    limit = PAGE_SIZE;
    render();
    if (updateUrl) {
      const url = new URL(window.location.href);
      if (active === 'all') url.searchParams.delete('series'); else url.searchParams.set('series', active);
      window.history.replaceState(null, '', url);
    }
  };

  filters.hidden = false;
  filters.addEventListener('click', (event) => {
    const button = event.target.closest('[data-filter]');
    if (button) select(button.dataset.filter);
  });
  more?.querySelector('[data-more-button]')?.addEventListener('click', () => {
    const firstNew = items.filter((item) => item.hidden && (active === 'all' || item.dataset.series === active))[0];
    limit += PAGE_SIZE;
    render();
    firstNew?.querySelector('a')?.focus({ preventScroll: true });
  });
  select(new URLSearchParams(window.location.search).get('series') || 'all', { updateUrl: false });
}

function readJson(selector) {
  try { return JSON.parse(document.querySelector(selector)?.textContent || '{}'); } catch { return {}; }
}

function initContact() {
  const copyButton = document.querySelector('[data-copy]');
  const copyStatus = document.querySelector('[data-copy-status]');
  copyButton?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(copyButton.dataset.copy);
      copyStatus.textContent = 'Email address copied.';
    } catch {
      copyStatus.textContent = `Copy this address: ${copyButton.dataset.copy}`;
    }
  });

  const form = document.querySelector('[data-composer]');
  if (!form) return;
  // Links such as "Ask about this photograph" pass ?works=...&series=...
  const params = new URLSearchParams(window.location.search);
  const workTitles = readJson('[data-work-titles]');
  const seriesTitles = readJson('[data-series-titles]');
  const named = [
    ...(params.get('works') || '').split(',').map((id) => workTitles[id.trim()]).filter(Boolean),
    ...(params.get('series') && !params.get('works') ? [seriesTitles[params.get('series')]] : []).filter(Boolean),
  ];
  if (named.length) form.elements.works.value = named.join(', ');
  const topic = params.get('inquiryType');
  if (topic && [...form.elements.topic.options].some((option) => option.text === topic)) form.elements.topic.value = topic;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const subject = `${form.elements.topic.value}${form.elements.works.value ? `: ${form.elements.works.value}` : ''}`;
    const body = `${form.elements.message.value.trim()}\n\n${form.elements.works.value ? `About: ${form.elements.works.value}\n` : ''}Sent from ${window.location.host}`;
    window.location.href = `mailto:${form.dataset.to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  });
}

// Old links such as /series.html?series=hamlet move to /series/hamlet/.
function redirectOldSeriesLinks() {
  const slug = new URLSearchParams(window.location.search).get('series');
  if (!slug || !/\/series(\.html)?$/.test(window.location.pathname)) return;
  if (/^[a-z0-9-]+$/.test(slug)) window.location.replace(`/series/${slug}/`);
}

redirectOldSeriesLinks();
initHeader();
initMenu();
initViewer();
initPortfolio();
initContact();
