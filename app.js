import { buildAbsoluteUrl, getSeriesBySlug, getWorkById, siteData } from './data.js';
import { clearSavedWorks, getSavedWorks } from './collection-tools.js';
function hasRealContactEmail(v) { return typeof v === 'string' && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim()); }
function hasRealPublicProfile(v) { return typeof v === 'string' && v.trim().startsWith('http'); }


const MAILTO_URL_LIMIT = 1800;
const STILLMRK_DEBUG = new URLSearchParams(window.location.search).has('debug') || window.localStorage?.getItem('stillmrk:debug') === '1';

function buildMailtoHref(to, subjectText, bodyText) {
  return `mailto:${to}?subject=${encodeURIComponent(subjectText)}&body=${encodeURIComponent(bodyText)}`;
}

async function copyTextSafely(text) {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}


const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const prefersReducedData = window.matchMedia?.('(prefers-reduced-data: reduce)').matches ?? false;
const mobileViewportQuery = window.matchMedia?.('(max-width: 760px)');

if (prefersReducedMotion) {
  document.documentElement.classList.remove('motion-ready');
} else {
  document.documentElement.classList.add('motion-ready');
}
const mobileNavBreakpoint = 980;
const lightboxEnabled = false;
const focusableSelectors = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',');


function getVisibleFocusableElements(root = document) {
  return [...root.querySelectorAll(focusableSelectors)].filter((element) => {
    if (!(element instanceof HTMLElement)) return false;
    if (element.disabled || element.hasAttribute('hidden')) return false;
    if (element.closest('[hidden], [aria-hidden="true"]')) return false;
    if (element.closest('[inert]')) return false;
    return element === document.activeElement || element.offsetParent !== null || element.getClientRects().length > 0;
  });
}

function setInertState(element, isInert) {
  if (!element) return;
  if ('inert' in element) {
    element.inert = Boolean(isInert);
  } else {
    element.toggleAttribute('data-inert-fallback', Boolean(isInert));
  }
}


const pageScrollLocks = new Set();
let lockedPageScrollY = 0;

function getPageScrollY() {
  const visualPageTop = window.visualViewport?.pageTop;
  if (Number.isFinite(visualPageTop)) return visualPageTop;
  return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
}

function restorePageScroll(y) {
  const targetY = Math.max(0, Number(y) || 0);
  window.scrollTo({ top: targetY, left: 0, behavior: 'auto' });
  document.documentElement.scrollTop = targetY;
  document.body.scrollTop = targetY;
}

function lockPageScroll(lockName) {
  if (!lockName) return;
  if (!pageScrollLocks.size) {
    lockedPageScrollY = getPageScrollY();
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }
    document.body.style.top = `-${lockedPageScrollY}px`;
  }
  pageScrollLocks.add(lockName);
  document.body.classList.add(lockName);
}

function unlockPageScroll(lockName) {
  if (!lockName) return;
  pageScrollLocks.delete(lockName);
  document.body.classList.remove(lockName);
  if (pageScrollLocks.size) return;

  const restoreY = lockedPageScrollY;
  lockedPageScrollY = 0;
  document.body.style.removeProperty('top');
  document.body.style.removeProperty('padding-right');
  restorePageScroll(restoreY);
}

function safeInit(label, callback) {
  try {
    callback();
  } catch (error) {
    if (STILLMRK_DEBUG) {
      // Keep production quiet while still allowing explicit local diagnostics.
      window.requestAnimationFrame(() => { throw new Error(`[STILLMRK] ${label} failed: ${error?.message || error}`); });
    }
  }
}

function setYear() {
  document.querySelectorAll('[data-year]').forEach((node) => {
    node.textContent = new Date().getFullYear();
  });
}

function hydrateSiteCopy() {
  const bindings = {
    siteName: siteData.site.name,
    artistName: siteData.artist.name,
    artistDiscipline: siteData.artist.discipline,
    artistTagline: siteData.artist.tagline,
    artistIntro: siteData.artist.intro,
    artistAbout: siteData.artist.about,
    artistStatement: siteData.artist.statement,
    artistStatus: siteData.artist.status,
    artistLocation: siteData.artist.location
  };

  Object.entries(bindings).forEach(([key, value]) => {
    const selector = `[data-${key.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`)}]`;
    document.querySelectorAll(selector).forEach((node) => {
      node.textContent = value;
    });
  });

  document.querySelectorAll('[data-artist-email]').forEach((node) => {
    if (hasRealContactEmail(siteData.artist.email)) {
      node.textContent = siteData.artist.email;
      node.setAttribute('href', `mailto:${siteData.artist.email}`);
    } else {
      node.removeAttribute('href');
      node.textContent = 'Available on request';
    }
  });

  document.querySelectorAll('[data-artist-instagram]').forEach((node) => {
    if (hasRealPublicProfile(siteData.artist.instagram)) {
      node.setAttribute('href', siteData.artist.instagram);
    } else {
      node.replaceWith(Object.assign(document.createElement('span'), { textContent: 'Not published on staging' }));
    }
  });
}

function initActiveNav() {
  const pathName = window.location.pathname.split('/').pop() || 'index.html';
  const fallbackPage = pathName.replace(/\.html$/i, '') || 'home';
  const page = document.body.dataset.page || (fallbackPage === 'index' ? 'home' : fallbackPage);
  const links = [...document.querySelectorAll('.site-nav a')];
  if (!links.length) return;

  links.forEach((link) => {
    const linkPage = link.dataset.page;
    const hrefPage = (link.getAttribute('href') || '').split('?')[0].split('/').pop().replace(/\.html$/i, '') || 'home';
    const isActive = linkPage === page || (page === 'home' && hrefPage === 'index') || hrefPage === page;
    link.classList.toggle('is-active', isActive);
    if (isActive) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });
}

function initProtocolNotice() {
  const notice = document.querySelector('[data-protocol-warning]');
  if (!notice) return;
  notice.hidden = window.location.protocol !== 'file:';
}

function initHeader() {
  const header = document.querySelector('[data-site-header]');
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.site-nav');
  if (!header || !toggle || !nav) return;

  const navLinks = [...nav.querySelectorAll('a')];
  let headerMetricFrame = 0;

  function updateHeaderMetrics() {
    window.cancelAnimationFrame(headerMetricFrame);
    headerMetricFrame = window.requestAnimationFrame(() => {
      const height = Math.ceil(header.getBoundingClientRect().height);
      if (height > 0) {
        document.documentElement.style.setProperty('--actual-header-height', `${height}px`);
      }
    });
  }

  function setNavLinksTabbable(isTabbable) {
    navLinks.forEach((link) => {
      if (isTabbable) link.removeAttribute('tabindex');
      else link.setAttribute('tabindex', '-1');
    });
  }

  function syncNavA11y(isOpen = false) {
    const isMobile = window.innerWidth <= mobileNavBreakpoint;
    // Do not use native inert on the nav panel itself. Some mobile browser
    // combinations keep inert descendants visually/semantically stale after
    // toggling, which can produce an expanded empty black menu. CSS handles
    // visibility; tabindex + aria-hidden handle keyboard/screen-reader state.
    nav.removeAttribute('inert');
    nav.removeAttribute('data-inert-fallback');
    if (isMobile) {
      nav.setAttribute('aria-hidden', String(!isOpen));
      setNavLinksTabbable(isOpen);
    } else {
      nav.removeAttribute('aria-hidden');
      setNavLinksTabbable(true);
    }
  }

  function closeMenu({ restoreFocus = false } = {}) {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open menu');
    nav.classList.remove('is-open');
    header.classList.remove('is-nav-open');
    syncNavA11y(false);
    if (restoreFocus) toggle.focus({ preventScroll: true });
  }

  function openMenu({ moveFocus = false } = {}) {
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Close menu');
    nav.classList.add('is-open');
    header.classList.add('is-nav-open');
    syncNavA11y(true);
    if (moveFocus) {
      window.requestAnimationFrame(() => {
        const firstLink = getVisibleFocusableElements(nav)[0];
        firstLink?.focus({ preventScroll: true });
      });
    }
  }

  function menuIsOpen() {
    return toggle.getAttribute('aria-expanded') === 'true';
  }

  function getMenuFocusableElements() {
    return [toggle, ...getVisibleFocusableElements(nav)].filter(Boolean);
  }

  function onScroll() {
    header.classList.toggle('is-scrolled', window.scrollY > 16);
  }

  updateHeaderMetrics();
  requestAnimationFrame(updateHeaderMetrics);
  if (document.fonts?.ready) {
    document.fonts.ready
      .then(() => requestAnimationFrame(updateHeaderMetrics))
      .catch(() => {});
  }
  window.addEventListener('resize', updateHeaderMetrics, { passive: true });
  window.visualViewport?.addEventListener('resize', updateHeaderMetrics, { passive: true });
  if ('ResizeObserver' in window) {
    new ResizeObserver(updateHeaderMetrics).observe(header);
  }

  nav.setAttribute('aria-label', nav.getAttribute('aria-label') || 'Primary navigation');
  syncNavA11y(false);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  toggle.addEventListener('click', (event) => {
    if (menuIsOpen()) {
      closeMenu();
    } else {
      openMenu({ moveFocus: event.detail === 0 });
    }
  });

  document.addEventListener('keydown', (event) => {
    if (!menuIsOpen()) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      closeMenu({ restoreFocus: true });
      return;
    }

    if (event.key !== 'Tab' || window.innerWidth > mobileNavBreakpoint) return;

    const focusable = getMenuFocusableElements();
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (!focusable.includes(document.activeElement)) {
      event.preventDefault();
      first.focus({ preventScroll: true });
      return;
    }

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  });

  navLinks.forEach((link) => link.addEventListener('click', () => closeMenu()));
  window.addEventListener('resize', () => {
    if (window.innerWidth > mobileNavBreakpoint) {
      closeMenu();
      syncNavA11y(false);
    } else {
      syncNavA11y(menuIsOpen());
    }
  }, { passive: true });
}

let revealObserver;

function registerRevealTargets(root = document) {
  const items = [...root.querySelectorAll('.reveal:not(.is-visible):not(.reveal--prepared)')];
  if (!items.length) return;

  if (prefersReducedMotion) {
    items.forEach((item) => item.classList.add('is-visible'));
    return;
  }

  items.forEach((item) => {
    item.classList.add('reveal--prepared');
    revealObserver?.observe(item);
  });
}

function initRevealObserver() {
  window.clearTimeout(window.STILLMRK_REVEAL_FALLBACK);
  document.documentElement.classList.remove('reveal-fallback');

  if (prefersReducedMotion) {
    document.documentElement.classList.remove('motion-ready');
    document.querySelectorAll('.reveal').forEach((item) => item.classList.add('is-visible'));
    return;
  }

  document.documentElement.classList.add('motion-ready');

  const revealThreshold = mobileViewportQuery?.matches ? 0.1 : 0.14;
  const revealRootMargin = mobileViewportQuery?.matches ? '0px 0px -36px 0px' : '0px 0px -80px 0px';

  revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      });
    },
    { threshold: revealThreshold, rootMargin: revealRootMargin }
  );

  registerRevealTargets();
}

function initScrollVariables() {
  if (prefersReducedMotion || prefersReducedData) return;

  let ticking = false;
  let lastProgress = -1;

  const update = () => {
    const root = document.documentElement;
    const max = Math.max(root.scrollHeight - window.innerHeight, 0);
    const progress = max > 0 ? window.scrollY / max : 0;
    const rounded = Math.min(Math.max(progress, 0), 1).toFixed(4);
    if (rounded !== lastProgress) {
      root.style.setProperty('--scroll-progress', rounded);
      lastProgress = rounded;
    }
    ticking = false;
  };

  const requestUpdate = () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  };

  update();
  window.addEventListener('scroll', requestUpdate, { passive: true });
  window.addEventListener('resize', requestUpdate, { passive: true });
  window.addEventListener('orientationchange', requestUpdate, { passive: true });
}


function ensureUtilitySection(referenceSelector, className, dataName) {
  const reference = document.querySelector(referenceSelector);
  if (!reference?.parentElement) return null;
  let section = document.querySelector(`[data-${dataName}]`);
  if (!section) {
    section = document.createElement('section');
    section.className = className;
    section.dataset[dataName] = 'true';
    reference.parentElement.insertBefore(section, reference);
  }
  return section;
}

function initResourcePanels() {
  const downloads = (siteData.downloads || []).filter((item) => item.audience !== 'private');
  if (!downloads.length) return;
  if (document.querySelector('[data-downloads-static]')) return;

  if (document.body.dataset.page === 'about') {
    const section = ensureUtilitySection('.site-footer', 'section section--compact', 'downloadsSection');
    if (!section) return;
    section.innerHTML = `
      <div class="container">
        <div class="section-head reveal section-head--tight">
          <div>
            <p class="eyebrow">Downloads</p>
            <h2 class="section-title">Press, exhibition, and profile documents.</h2>
            <p class="section-intro">These files make the portfolio easier to review without forcing people to copy details from the site by hand.</p>
          </div>
        </div>
        <div class="download-grid">
          ${downloads.map((item) => `
            <article class="download-card panel reveal">
              <p class="eyebrow">${item.kind || 'Document'}</p>
              <h3>${item.title}</h3>
              <p>${item.description || ''}</p>
              <a class="button button--secondary" href="${item.file}" target="_blank" rel="noreferrer">Open document</a>
            </article>
          `).join('')}
        </div>
      </div>
    `;
  }

  if (document.body.dataset.page === 'contact') {
    const form = document.querySelector('[data-contact-form]');
    if (!form) return;
    let panel = document.querySelector('[data-contact-downloads]');
    if (!panel) {
      panel = document.createElement('aside');
      panel.className = 'contact-downloads panel reveal';
      panel.dataset.contactDownloads = 'true';
      form.parentElement?.insertBefore(panel, form);
    }
    panel.innerHTML = `
      <p class="eyebrow">Downloads</p>
      <h2 class="section-title">Useful documents before you write.</h2>
      <div class="contact-downloads__list">
        ${downloads.slice(0, 3).map((item) => `
          <a class="contact-downloads__item" href="${item.file}" target="_blank" rel="noreferrer">
            <strong>${item.title}</strong>
            <span>${item.description || ''}</span>
          </a>
        `).join('')}
      </div>
    `;
  }
}

function initContactEnhancements() {
  const form = document.querySelector('[data-contact-form]');
  if (!form) return;

  const params = new URLSearchParams(window.location.search);
  const requestedIds = (params.get('works') || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  const requestedWorks = requestedIds.map((id) => getWorkById(id)).filter(Boolean);
  const shortlistWorks = params.get('useShortlist') === '1' ? getSavedWorks() : [];
  const works = requestedWorks.length ? requestedWorks : shortlistWorks;
  const series = getSeriesBySlug(params.get('series') || '');
  const inquiryType = params.get('inquiryType') || '';

  const inquiryField = form.querySelector('[name="inquiryType"]');
  if (inquiryField && inquiryType) inquiryField.value = inquiryType;

  const messageField = form.querySelector('[name="message"]');
  if (messageField && !messageField.value.trim() && (works.length || series)) {
    const lines = [];
    if (series) lines.push(`Series: ${series.title}`);
    if (works.length) lines.push(`Selected works: ${works.map((work) => work.title).join(', ')}`);
    if (series?.projectType) lines.push(`Project type: ${series.projectType}`);
    if (lines.length) messageField.value = `${lines.join('\n')}\n\nPlease share availability, pricing, and next steps.`;
  }

  if (!works.length && !series) return;

  let summary = document.querySelector('[data-contact-shortlist]');
  if (!summary) {
    summary = document.createElement('div');
    summary.className = 'contact-shortlist panel panel--soft reveal';
    summary.dataset.contactShortlist = 'true';
    form.insertAdjacentElement('beforebegin', summary);
  }

  summary.innerHTML = `
    <p class="eyebrow">Inquiry context</p>
    <h2 class="section-title">${series ? series.title : 'Selected works'}</h2>
    <p>${works.length ? `This draft includes ${works.length} selected work${works.length === 1 ? '' : 's'}.` : 'This inquiry is linked to the selected series.'}</p>
    ${works.length ? `<ul class="contact-shortlist__list">${works.map((work) => `<li>${work.title}<span>${(work.caption || '').trim() || `${work.location} · ${work.year}`}</span></li>`).join('')}</ul>` : ''}
    <div class="contact-shortlist__actions">
      <button class="button button--ghost" type="button" data-contact-clear-shortlist ${requestedWorks.length ? 'hidden' : ''}>Clear shortlist</button>
      <a class="button button--secondary" href="portfolio.html${series ? `?series=${encodeURIComponent(series.slug)}` : ''}">Back to archive</a>
    </div>
  `;

  summary.querySelector('[data-contact-clear-shortlist]')?.addEventListener('click', () => {
    clearSavedWorks();
    summary.remove();
  });
}

function initContactForm() {
  const form = document.querySelector('[data-contact-form]');
  const status = document.querySelector('[data-form-status]');
  if (!form || !status) return;

  const submitButton = form.querySelector('button[type="submit"]');
  const copyEmailButton = form.querySelector('[data-copy-artist-email]');
  const endpoint = String(form.dataset.contactEndpoint || '').trim();
  const hasEndpoint = /^https?:\/\//i.test(endpoint);

  const setStatus = (state, message) => {
    status.dataset.state = state || '';
    status.textContent = message;
    status.setAttribute('role', state === 'warning' ? 'alert' : 'status');
    status.setAttribute('aria-live', state === 'warning' ? 'assertive' : 'polite');
    status.setAttribute('aria-atomic', 'true');
  };

  const defaultMessage = hasEndpoint
    ? 'Send the inquiry directly from the site. If the submission fails, use the direct email options below.'
    : 'This form prepares a structured draft. If no mail app responds, use the direct email options below.';

  const resetStatus = () => setStatus('', defaultMessage);
  resetStatus();

  form.addEventListener('input', (event) => {
    resetStatus();
    event.target?.removeAttribute?.('aria-invalid');
  });
  form.addEventListener('change', (event) => {
    event.target?.removeAttribute?.('aria-invalid');
  });

  const markInvalidFields = () => {
    const fields = [...form.querySelectorAll('input, select, textarea')];
    fields.forEach((field) => field.removeAttribute('aria-invalid'));
    const invalidField = fields.find((field) => typeof field.checkValidity === 'function' && !field.checkValidity());
    if (!invalidField) return false;

    invalidField.setAttribute('aria-invalid', 'true');
    const label = invalidField.closest('label')?.querySelector('span')?.textContent?.trim() || 'the required field';
    setStatus('warning', `Complete ${label.toLowerCase()} before continuing.`);
    invalidField.focus({ preventScroll: false });
    window.setTimeout(() => {
      invalidField.scrollIntoView({
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
        block: 'center'
      });
    }, 80);
    return true;
  };

  copyEmailButton?.addEventListener('click', async () => {
    if (!hasRealContactEmail(siteData.artist.email)) {
      setStatus('warning', 'Update the contact email in content/artist.yaml, then run python build_site.py before publishing.');
      return;
    }
    const copied = await copyTextSafely(siteData.artist.email);
    setStatus(copied ? 'success' : 'warning', copied ? 'Email address copied. Paste it into your mail app.' : 'Copying failed in this browser. Use the email address shown above.');
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!form.checkValidity()) {
      markInvalidFields();
      return;
    }

    if (!hasRealContactEmail(siteData.artist.email)) {
      setStatus('warning', 'Update the contact email in content/artist.yaml, then run python build_site.py before publishing. The inquiry cannot continue until that address is real.');
      return;
    }

    const data = new FormData(form);
    const name = String(data.get('name') || '').trim();
    const email = String(data.get('email') || '').trim();
    const inquiryType = String(data.get('inquiryType') || '').trim();
    const timeline = String(data.get('timeline') || '').trim();
    const message = String(data.get('message') || '').trim();
    const subjectText = `STILLMRK inquiry - ${inquiryType} - ${name}`;
    const bodyText = [
      `Name: ${name}`,
      `Email: ${email}`,
      `Inquiry type: ${inquiryType}`,
      timeline ? `Timeline: ${timeline}` : null,
      '',
      message
    ]
      .filter(Boolean)
      .join('\n');

    if (hasEndpoint) {
      const payload = new FormData(form);
      payload.append('_subject', subjectText);
      submitButton?.setAttribute('disabled', 'disabled');
      setStatus('', 'Sending inquiry…');
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          body: payload,
          headers: { Accept: 'application/json' }
        });
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);
        form.reset();
        setStatus('success', 'Inquiry sent. If you do not receive a reply, use the direct email address below as a fallback.');
      } catch {
        setStatus('warning', 'The direct form submission did not complete. Use the direct email options below instead.');
      } finally {
        submitButton?.removeAttribute('disabled');
      }
      return;
    }

    let href = buildMailtoHref(siteData.artist.email, subjectText, bodyText);
    let copied = false;
    let compacted = false;

    if (href.length > MAILTO_URL_LIMIT) {
      compacted = true;
      copied = await copyTextSafely(bodyText);
      const compactBody = [
        `Name: ${name}`,
        `Email: ${email}`,
        `Inquiry type: ${inquiryType}`,
        timeline ? `Timeline: ${timeline}` : null,
        '',
        'The full message was too long for a reliable mailto URL.',
        copied ? 'The complete text has been copied to your clipboard. Paste it into the email body after your mail app opens.' : 'Please paste your full message into the email body after your mail app opens.',
        '',
        `Message preview: ${message.slice(0, 280)}${message.length > 280 ? '…' : ''}`
      ]
        .filter(Boolean)
        .join('\n');
      href = buildMailtoHref(siteData.artist.email, subjectText, compactBody);
    }

    setStatus('', compacted
      ? (copied
        ? 'Trying to open your mail app with a shorter draft. The full message has also been copied to your clipboard.'
        : 'Trying to open your mail app with a shorter draft. If it opens, paste your full message into the body.')
      : 'Trying to open your mail app. If nothing happens, use the direct email options below.');

    let pageHidden = false;
    const markHidden = () => {
      pageHidden = true;
    };
    window.addEventListener('pagehide', markHidden, { once: true });

    window.location.href = href;

    window.setTimeout(() => {
      if (!pageHidden && document.hasFocus()) {
        setStatus('warning', copied
          ? 'No mail app responded. The full message is on your clipboard, and the direct email options are below.'
          : 'No mail app responded. Use the direct email options below.');
      }
    }, 1200);
  });
}


function initMobileFormComfort(root = document) {
  const form = root.querySelector('[data-contact-form]');
  if (form) {
    form.setAttribute('novalidate', '');
    form.querySelectorAll('input, select, textarea').forEach((field) => {
      field.addEventListener('input', () => field.removeAttribute('aria-invalid'));
      field.addEventListener('change', () => field.removeAttribute('aria-invalid'));
    });
  }

  root.querySelectorAll('textarea').forEach((textarea) => {
    if (textarea.dataset.mobileFocusComfortInit) return;
    textarea.dataset.mobileFocusComfortInit = 'true';
    textarea.addEventListener('focus', () => {
      window.setTimeout(() => {
        textarea.scrollIntoView({
          behavior: prefersReducedMotion ? 'auto' : 'smooth',
          block: 'center'
        });
      }, 300);
    });
  });
}


function initExpandableInfoCards(root = document) {
  const cards = [...root.querySelectorAll('.info-card')].filter((card) => !card.dataset.expandableCopyInit);
  cards.forEach((card, index) => {
    const copy = card.querySelector('p');
    if (!copy || copy.textContent.trim().length < 180) return;

    card.dataset.expandableCopy = 'true';
    card.dataset.expandableCopyInit = 'true';
    card.classList.add('is-copy-collapsed');

    if (!copy.id) copy.id = `info-card-copy-${index + 1}`;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'info-card__expand';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', copy.id);
    button.textContent = 'Read more';

    button.addEventListener('click', () => {
      const expanded = card.classList.toggle('is-copy-expanded');
      card.classList.toggle('is-copy-collapsed', !expanded);
      button.setAttribute('aria-expanded', String(expanded));
      button.textContent = expanded ? 'Show less' : 'Read more';
    });

    copy.insertAdjacentElement('afterend', button);
  });
}

function initMobileContactBar() {
  const bar = document.querySelector('[data-mobile-contact-bar]');
  const form = document.querySelector('[data-contact-form]');
  if (!bar || !form || bar.dataset.mobileContactBarInit) return;
  bar.dataset.mobileContactBarInit = 'true';
  bar.setAttribute('aria-hidden', 'true');

  const mobileQuery = window.matchMedia('(max-width: 760px)');

  const formIsVisible = () => {
    const rect = form.getBoundingClientRect();
    const viewportHeight = window.visualViewport?.height || window.innerHeight || 0;
    if (!viewportHeight) return false;
    return rect.bottom > viewportHeight * 0.18 && rect.top < viewportHeight * 0.82;
  };

  const updateVisibility = (isFormVisible = formIsVisible()) => {
    const shouldShow = mobileQuery.matches && !isFormVisible;
    bar.classList.toggle('is-visible', shouldShow);
    bar.setAttribute('aria-hidden', String(!shouldShow));
    document.body.classList.toggle('mobile-contact-bar-open', shouldShow);
  };

  let ticking = false;
  const scheduleUpdate = () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(() => {
      updateVisibility();
      ticking = false;
    });
  };

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        updateVisibility(Boolean(entry?.isIntersecting));
      },
      { threshold: [0, 0.08, 0.24], rootMargin: '0px 0px -35% 0px' }
    );
    observer.observe(form);
  }

  form.addEventListener('focusin', () => updateVisibility(true));
  form.addEventListener('focusout', scheduleUpdate);
  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate, { passive: true });
  window.addEventListener('orientationchange', scheduleUpdate, { passive: true });
  mobileQuery.addEventListener?.('change', scheduleUpdate);
  updateVisibility();
}

function initLightbox() {
  const dialog = document.querySelector('[data-lightbox]');
  if (!dialog) return;
  if (!lightboxEnabled) {
    dialog.setAttribute('hidden', '');
    return;
  }

  const source = dialog.querySelector('[data-lightbox-source]');
  const image = dialog.querySelector('[data-lightbox-image]');
  const title = dialog.querySelector('[data-lightbox-title]');
  const meta = dialog.querySelector('[data-lightbox-meta]');
  const counter = dialog.querySelector('[data-lightbox-counter]');
  const caption = dialog.querySelector('[data-lightbox-caption]');
  const closeButton = dialog.querySelector('[data-lightbox-close]');
  const prevButton = dialog.querySelector('[data-lightbox-prev]');
  const nextButton = dialog.querySelector('[data-lightbox-next]');
  const media = dialog.querySelector('.lightbox__media');
  const figure = dialog.querySelector('[data-lightbox-figure]');
  const pageRegions = [
    document.querySelector('[data-site-header]'),
    document.querySelector('main'),
    document.querySelector('.site-footer')
  ].filter(Boolean);

  let items = [];
  let currentIndex = 0;
  let activeGroup = 'default';
  let lastTrigger = null;
  let touchStartX = 0;
  let touchStartY = 0;
  let touchDeltaX = 0;
  let touchDeltaY = 0;
  let isSwiping = false;
  let lightboxAnimationTimer = 0;

  function markLightboxAnimating(duration = 260) {
    if (!dialog) return;
    dialog.classList.add('lightbox--animating');
    window.clearTimeout(lightboxAnimationTimer);
    lightboxAnimationTimer = window.setTimeout(() => {
      dialog.classList.remove('lightbox--animating');
    }, duration);
  }

  function setBackgroundInteractive(isInteractive) {
    pageRegions.forEach((region) => {
      if ('inert' in region) {
        region.inert = !isInteractive;
        if (isInteractive) region.removeAttribute('aria-hidden');
      } else if (isInteractive) {
        region.removeAttribute('aria-hidden');
      } else {
        region.setAttribute('aria-hidden', 'true');
      }
    });
  }

  function collectItems(group = activeGroup) {
    activeGroup = group || 'default';
    const escapedGroup = window.CSS?.escape ? window.CSS.escape(activeGroup) : activeGroup.replace(/[\'\\]/g, '\\$&');
    items = [...document.querySelectorAll(`[data-lightbox-src][data-lightbox-group="${escapedGroup}"]`)];
  }

  function preloadNearby(index) {
    if (prefersReducedData || items.length <= 1) return;

    [-1, 1].forEach((offset) => {
      const item = items[(index + offset + items.length) % items.length];
      if (!item) return;
      const preloadImage = new Image();
      preloadImage.decoding = 'async';
      preloadImage.srcset = item.dataset.lightboxJpgSrcset || '';
      preloadImage.sizes = item.dataset.lightboxSizes || '92vw';
      preloadImage.src = item.dataset.lightboxSrc || '';
    });
  }

  function setLightboxCounter(text, label) {
    if (!counter) return;

    const apply = () => {
      counter.textContent = text;
      counter.setAttribute('aria-label', label);
    };

    if (prefersReducedMotion || !counter.textContent.trim()) {
      apply();
      return;
    }

    counter.classList.add('is-updating');
    window.setTimeout(() => {
      apply();
      window.requestAnimationFrame(() => counter.classList.remove('is-updating'));
    }, 90);
  }

  function updateButtons() {
    const isSingle = items.length <= 1;
    prevButton?.toggleAttribute('disabled', isSingle);
    nextButton?.toggleAttribute('disabled', isSingle);
  }

  function update(index) {
    if (!items.length) return;
    markLightboxAnimating();

    currentIndex = (index + items.length) % items.length;
    const trigger = items[currentIndex];

    if (source) {
      source.srcset = trigger.dataset.lightboxWebpSrcset || '';
      source.sizes = trigger.dataset.lightboxSizes || '92vw';
    }

    image.src = trigger.dataset.lightboxSrc || '';
    image.srcset = trigger.dataset.lightboxJpgSrcset || '';
    image.sizes = trigger.dataset.lightboxSizes || '92vw';
    image.alt = trigger.dataset.lightboxAlt || trigger.dataset.lightboxTitle || 'Selected photograph';
    image.width = Number(trigger.dataset.lightboxWidth) || image.width;
    image.height = Number(trigger.dataset.lightboxHeight) || image.height;
    image.loading = 'eager';
    image.decoding = 'async';

    if (media) {
      const width = Number(trigger.dataset.lightboxWidth) || 1;
      const height = Number(trigger.dataset.lightboxHeight) || 1;
      media.style.setProperty('--media-ratio', `${width} / ${height}`);
    }

    title.textContent = trigger.dataset.lightboxTitle || '';
    dialog.setAttribute('aria-label', title.textContent ? `Image viewer: ${title.textContent}` : 'Image viewer');
    const lightboxMeta = trigger.dataset.lightboxMeta || '';
    const lightboxCaption = trigger.dataset.lightboxCaption || '';
    meta.textContent = lightboxCaption ? `${lightboxMeta} · ${lightboxCaption}` : lightboxMeta;
    meta.setAttribute('aria-live', 'polite');
    setLightboxCounter(
      `${String(currentIndex + 1).padStart(2, '0')} / ${String(items.length).padStart(2, '0')}`,
      `Image ${currentIndex + 1} of ${items.length}`
    );
    figure?.focus({ preventScroll: true });

    updateButtons();
    preloadNearby(currentIndex);
  }

  function trapFocus(event) {
    if (event.key !== 'Tab') return;
    const focusable = [...dialog.querySelectorAll(focusableSelectors)].filter(
      (element) => element.offsetParent !== null || element === document.activeElement
    );
    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function open(index, trigger) {
    const group = trigger?.dataset.lightboxGroup || 'default';
    collectItems(group);
    if (!items.length) return;

    lastTrigger = trigger || document.activeElement;
    update(index);

    if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
    else dialog.setAttribute('open', '');

    dialog.removeAttribute('aria-hidden');
    lockPageScroll('dialog-open');
    setBackgroundInteractive(false);
    closeButton?.focus();
  }

  function close() {
    if (typeof dialog.close === 'function' && dialog.open) dialog.close();
    else dialog.removeAttribute('open');

    dialog.setAttribute('aria-hidden', 'true');
    unlockPageScroll('dialog-open');
    setBackgroundInteractive(true);

    touchStartX = 0;
    touchStartY = 0;
    touchDeltaX = 0;
    touchDeltaY = 0;
    isSwiping = false;
    figure?.style.removeProperty('transform');

    image.removeAttribute('src');
    image.removeAttribute('srcset');
    image.removeAttribute('sizes');
    source?.removeAttribute('srcset');
    source?.removeAttribute('sizes');

    if (lastTrigger instanceof HTMLElement) lastTrigger.focus();
  }

  function handleTouchStart(event) {
    if (!dialog.open) return;
    const touch = event.changedTouches[0];
    touchStartX = touch?.clientX || 0;
    touchStartY = touch?.clientY || 0;
    touchDeltaX = 0;
    touchDeltaY = 0;
    isSwiping = true;
    markLightboxAnimating(420);
  }

  function handleTouchMove(event) {
    if (!isSwiping) return;
    const touch = event.changedTouches[0];
    const currentX = touch?.clientX || touchStartX;
    const currentY = touch?.clientY || touchStartY;
    touchDeltaX = currentX - touchStartX;
    touchDeltaY = currentY - touchStartY;
    const horizontalIntent = Math.abs(touchDeltaX) > Math.abs(touchDeltaY);
    const verticalIntent = Math.abs(touchDeltaY) > 24 && Math.abs(touchDeltaY) > Math.abs(touchDeltaX);
    if (horizontalIntent || verticalIntent) event.preventDefault();

    if (horizontalIntent && items.length > 1) {
      const clamped = Math.max(Math.min(touchDeltaX, 72), -72);
      figure?.style.setProperty('transform', `translateX(${clamped}px)`);
    } else if (verticalIntent) {
      const clampedY = Math.max(Math.min(touchDeltaY, 72), -72);
      figure?.style.setProperty('transform', `translateY(${clampedY}px)`);
    } else {
      figure?.style.removeProperty('transform');
    }
  }

  function handleTouchEnd(event) {
    if (!isSwiping) return;
    const touch = event.changedTouches[0];
    const endX = touch?.clientX || touchStartX;
    const endY = touch?.clientY || touchStartY;
    const deltaX = endX - touchStartX;
    const deltaY = endY - touchStartY;
    const shouldDismiss = Math.abs(deltaY) > 120 && Math.abs(deltaY) > Math.abs(deltaX);
    isSwiping = false;
    touchStartX = 0;
    touchStartY = 0;
    touchDeltaX = 0;
    touchDeltaY = 0;
    figure?.style.removeProperty('transform');
    markLightboxAnimating(220);

    if (shouldDismiss) {
      close();
      return;
    }

    if (items.length <= 1) return;
    if (deltaX > 40) update(currentIndex - 1);
    else if (deltaX < -40) update(currentIndex + 1);
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-lightbox-src]');
    if (!trigger) return;
    event.preventDefault();
    collectItems(trigger.dataset.lightboxGroup || 'default');
    open(items.indexOf(trigger), trigger);
  });

  closeButton?.addEventListener('click', close);
  prevButton?.addEventListener('click', () => update(currentIndex - 1));
  nextButton?.addEventListener('click', () => update(currentIndex + 1));
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close();
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) close();
  });

  figure?.addEventListener('touchstart', handleTouchStart, { passive: true });
  figure?.addEventListener('touchmove', handleTouchMove, { passive: false });
  figure?.addEventListener('touchend', handleTouchEnd, { passive: true });
  figure?.addEventListener('touchcancel', handleTouchEnd, { passive: true });

  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      update(currentIndex - 1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      update(currentIndex + 1);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else {
      trapFocus(event);
    }
  });
}



function initInteractionA11y(root = document) {
  root.querySelectorAll('[data-filter-row]').forEach((row) => {
    row.setAttribute('aria-label', row.getAttribute('aria-label') || 'Filter portfolio by series');
    row.querySelectorAll('.filter-chip').forEach((chip) => {
      const active = chip.classList.contains('is-active') || chip.getAttribute('aria-pressed') === 'true';
      if (active) chip.setAttribute('aria-current', 'true');
      else chip.removeAttribute('aria-current');
    });
  });

  root.querySelectorAll('[data-work-count]').forEach((node) => {
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    node.setAttribute('aria-atomic', 'true');
  });

  root.querySelectorAll('[data-series-access-status], [data-form-status]').forEach((node) => {
    if (!node.id) node.id = node.matches('[data-form-status]') ? 'contact-form-status' : 'series-access-status';
    node.setAttribute('role', node.dataset.state === 'warning' ? 'alert' : 'status');
    node.setAttribute('aria-live', node.dataset.state === 'warning' ? 'assertive' : 'polite');
    node.setAttribute('aria-atomic', 'true');
  });

  const contactStatus = root.querySelector('[data-form-status]');
  const contactForm = root.querySelector('[data-contact-form]');
  if (contactStatus && contactForm) {
    contactForm.querySelectorAll('input, select, textarea').forEach((field) => {
      const describedBy = new Set(String(field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
      describedBy.add(contactStatus.id);
      field.setAttribute('aria-describedby', [...describedBy].join(' '));
    });
  }

  root.querySelectorAll('[data-lightbox-src]').forEach((trigger) => {
    const title = trigger.dataset.lightboxTitle || trigger.querySelector('img')?.alt || 'photograph';
    if (!trigger.getAttribute('aria-label')) {
      trigger.setAttribute('aria-label', `Open ${title} in image viewer`);
    }
  });
}

function initMediaAspectRatios(root = document) {
  const mediaSelectors = [
    '.hero__visual',
    '.about-hero__visual',
    '.series-masthead__visual',
    '.page-hero__visual',
    '.work-card__media',
    '.series-card__media',
    '.editorial-card__media',
    '.series-frame__media',
    '.feature-module__visual',
    '.lightbox__media'
  ].join(',');

  root.querySelectorAll(mediaSelectors).forEach((media) => {
    if (media.style.getPropertyValue('--media-ratio')) return;
    const image = media.querySelector('img');
    if (!image) return;

    const width = Number(image.getAttribute('width') || image.naturalWidth || image.dataset.lightboxWidth || 0);
    const height = Number(image.getAttribute('height') || image.naturalHeight || image.dataset.lightboxHeight || 0);
    if (!width || !height) return;

    media.style.setProperty('--media-ratio', `${width} / ${height}`);
  });
}

function initMediaLoadStates(root = document) {
  const mediaSelectors = [
    '.hero__visual',
    '.about-hero__visual',
    '.series-masthead__visual',
    '.page-hero__visual',
    '.work-card__media',
    '.series-card__media',
    '.editorial-card__media',
    '.series-frame__media',
    '.feature-module__visual'
  ].join(',');

  root.querySelectorAll(mediaSelectors).forEach((media) => {
    const image = media.querySelector('img');
    if (!image) return;

    const clearLoadingState = () => media.classList.remove('is-loading');
    if (image.complete && image.naturalWidth > 0) {
      clearLoadingState();
      return;
    }

    media.classList.add('is-loading');
    image.addEventListener('load', clearLoadingState, { once: true });
    image.addEventListener('error', clearLoadingState, { once: true });
  });
}

function initProtectedMedia() {
  const protectedSelector = [
    'img',
    'picture',
    '[data-protect-media]',
    '.hero__visual',
    '.about-hero__visual',
    '.page-hero__visual',
    '.series-masthead__visual',
    '.lightbox__media',
    '[data-lightbox-src]'
  ].join(',');

  let notice;
  let noticeTimer;

  const showNotice = () => {
    if (!notice) {
      notice = document.createElement('div');
      notice.className = 'protected-media-notice';
      notice.setAttribute('role', 'status');
      notice.setAttribute('aria-live', 'polite');
      notice.textContent = 'Image saving is disabled on this portfolio.';
      document.body.append(notice);
    }

    window.clearTimeout(noticeTimer);
    notice.classList.add('is-visible');
    noticeTimer = window.setTimeout(() => {
      notice?.classList.remove('is-visible');
    }, 1800);
  };

  const protectImages = (root = document) => {
    root.querySelectorAll('img').forEach((image) => {
      image.draggable = false;
      image.setAttribute('draggable', 'false');
      image.addEventListener('dragstart', (event) => event.preventDefault());
    });
  };

  protectImages();

  const block = (event, announce = false) => {
    event.preventDefault();
    if (announce) showNotice();
  };

  document.addEventListener('contextmenu', (event) => block(event, true), { capture: true });

  document.addEventListener('dragstart', (event) => {
    if (!event.target.closest(protectedSelector)) return;
    block(event);
  }, { capture: true });

  document.addEventListener('selectstart', (event) => {
    if (!event.target.closest(protectedSelector)) return;
    block(event);
  }, { capture: true });

  document.addEventListener('keydown', (event) => {
    const key = event.key.toLowerCase();
    const isSaveShortcut = (event.ctrlKey || event.metaKey) && key === 's';
    if (!isSaveShortcut) return;
    block(event, true);
  }, { capture: true });

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        if (node.matches('img')) {
          node.draggable = false;
          node.setAttribute('draggable', 'false');
        }
        protectImages(node);
      });
    });
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });
}


function initSeriesScrollDots(root = document) {
  const tracks = [...root.querySelectorAll('.series-card-grid')].filter(
    (track) => !track.dataset.scrollDotsInit
      && !track.classList.contains('series-card-grid--performance')
      && track.dataset.scrollDots !== 'false'
      && track.closest('body')?.dataset.page !== 'performance'
  );

  tracks.forEach((track) => {
    const cards = [...track.querySelectorAll('.series-card')];
    if (cards.length < 2) return;

    track.dataset.scrollDotsInit = 'true';
    const dots = document.createElement('div');
    dots.className = 'scroll-dots';
    dots.setAttribute('aria-hidden', 'true');

    const dotNodes = cards.map((_, index) => {
      const dot = document.createElement('span');
      dot.className = 'scroll-dots__dot';
      dot.dataset.index = String(index);
      dots.append(dot);
      return dot;
    });

    track.insertAdjacentElement('afterend', dots);

    const update = () => {
      const trackRect = track.getBoundingClientRect();
      const center = trackRect.left + trackRect.width / 2;
      let activeIndex = 0;
      let closestDistance = Number.POSITIVE_INFINITY;

      cards.forEach((card, index) => {
        const cardRect = card.getBoundingClientRect();
        const cardCenter = cardRect.left + cardRect.width / 2;
        const distance = Math.abs(cardCenter - center);
        if (distance < closestDistance) {
          closestDistance = distance;
          activeIndex = index;
        }
      });

      dotNodes.forEach((dot, index) => {
        dot.classList.toggle('is-active', index === activeIndex);
      });
    };

    let ticking = false;
    const scheduleUpdate = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        update();
        ticking = false;
      });
    };

    track.addEventListener('scroll', scheduleUpdate, { passive: true });
    window.addEventListener('resize', scheduleUpdate, { passive: true });
    update();
  });
}

function initAdaptiveImagePriority() {
  if (prefersReducedData || !('IntersectionObserver' in window)) return;

  const promoted = new WeakSet();
  const mediaRootMargin = mobileViewportQuery?.matches ? '420px 0px 420px 0px' : '280px 0px 280px 0px';
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const media = entry.target;
        const image = media.querySelector('img[loading="lazy"]');
        if (!image || promoted.has(image)) {
          observer.unobserve(media);
          return;
        }

        promoted.add(image);
        image.loading = 'eager';
        image.fetchPriority = 'high';
        observer.unobserve(media);
      });
    },
    { rootMargin: mediaRootMargin, threshold: 0.01 }
  );

  const observeCandidates = () => {
    document.querySelectorAll('[data-priority-candidate]').forEach((media) => {
      const image = media.querySelector('img');
      if (!image || promoted.has(image)) return;
      observer.observe(media);
    });
  };

  observeCandidates();
  document.addEventListener('stillmrk:refresh', observeCandidates);
}


function ensureMeta(selector, createTag, attributes = {}) {
  let element = document.querySelector(selector);
  if (!element) {
    element = document.createElement(createTag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    document.head.append(element);
  }
  return element;
}

function injectUrlMetadata() {
  const canonical = document.querySelector('link[rel="canonical"]');
  const ogUrl = document.querySelector('meta[property="og:url"]');
  const fallbackUrl = buildAbsoluteUrl(window.location.pathname + window.location.search).split('#')[0];

  if (!canonical) {
    ensureMeta('link[rel="canonical"]', 'link', { rel: 'canonical' }).setAttribute('href', fallbackUrl);
  }

  if (!ogUrl) {
    ensureMeta('meta[property="og:url"]', 'meta', { property: 'og:url' }).setAttribute('content', fallbackUrl);
  }
}

function injectStructuredData() {
  const baseScript = document.querySelector('[data-base-schema]');
  const pageScript = document.querySelector('[data-page-schema]');
  const pageDescription = document.querySelector('meta[name="description"]')?.getAttribute('content') || siteData.site.description;
  const pageTitle = document.title;
  const siteUrl = siteData.site.siteUrl || siteData.site.displayUrl || buildAbsoluteUrl('/');
  const pageUrl = window.location.href.split('#')[0];

  if (baseScript) {
    const person = {
      '@type': 'Person',
      '@id': `${siteUrl}#person`,
      name: siteData.artist.name,
      alternateName: siteData.artist.alternateNames || [],
      jobTitle: siteData.artist.discipline,
      description: siteData.artist.about,
      homeLocation: siteData.artist.location,
      url: siteUrl
    };

    if (hasRealContactEmail(siteData.artist.email)) person.email = siteData.artist.email;
    if (hasRealPublicProfile(siteData.artist.instagram)) person.sameAs = [siteData.artist.instagram];

    baseScript.textContent = JSON.stringify(
      {
        '@context': 'https://schema.org',
        '@graph': [
          {
            '@type': 'WebSite',
            '@id': `${siteUrl}#website`,
            name: siteData.site.name,
            description: siteData.site.description,
            url: siteUrl,
            image: buildAbsoluteUrl(siteData.site.ogImage),
            publisher: { '@id': `${siteUrl}#person` }
          },
          person
        ]
      },
      null,
      2
    );
  }

  if (pageScript && !pageScript.textContent.trim()) {
    const page = document.body.dataset.page;
    const pageTypes = {
      home: 'CollectionPage',
      portfolio: 'CollectionPage',
      about: 'ProfilePage',
      contact: 'ContactPage',
      series: 'CollectionPage'
    };
    const pageSchema = {
      '@context': 'https://schema.org',
      '@type': pageTypes[page] || 'WebPage',
      name: pageTitle,
      description: pageDescription,
      url: pageUrl,
      inLanguage: 'en-GB',
      image: buildAbsoluteUrl(document.querySelector('meta[property="og:image"]')?.getAttribute('content') || siteData.site.ogImage),
      isPartOf: {
        '@id': `${siteUrl}#website`,
        '@type': 'WebSite',
        name: siteData.site.name,
        url: siteUrl
      },
      author: { '@id': `${siteUrl}#person` },
      creator: { '@id': `${siteUrl}#person` }
    };
    if (page === 'about') {
      pageSchema.mainEntity = { '@id': `${siteUrl}#person` };
    }
    pageScript.textContent = JSON.stringify(pageSchema, null, 2);
  }
}

async function initPageModule() {
  const page = document.body.dataset.page;
  const loaders = {
    portfolio: () => import('./portfolio.js'),
    series: () => import('./series.js')
  };

  if (!loaders[page]) return;
  await loaders[page]();
}

document.addEventListener('stillmrk:refresh', () => registerRevealTargets());
document.addEventListener('stillmrk:refresh', () => initMediaAspectRatios());
document.addEventListener('stillmrk:refresh', () => initMediaLoadStates());
document.addEventListener('stillmrk:refresh', () => initSeriesScrollDots());
document.addEventListener('stillmrk:refresh', () => initInteractionA11y());

document.addEventListener('DOMContentLoaded', async () => {
  const initializers = [
    ['setYear', setYear],
    ['hydrateSiteCopy', hydrateSiteCopy],
    ['initProtocolNotice', initProtocolNotice],
    ['initActiveNav', initActiveNav],
    ['initHeader', initHeader],
    ['initRevealObserver', initRevealObserver],
    ['initScrollVariables', initScrollVariables],
    ['initResourcePanels', initResourcePanels],
    ['initContactEnhancements', initContactEnhancements],
    ['initContactForm', initContactForm],
    ['initMobileFormComfort', initMobileFormComfort],
    ['initExpandableInfoCards', initExpandableInfoCards],
    ['initMobileContactBar', initMobileContactBar],
    ['initLightbox', initLightbox],
    ['initProtectedMedia', initProtectedMedia],
    ['initMediaAspectRatios', initMediaAspectRatios],
    ['initMediaLoadStates', initMediaLoadStates],
    ['initSeriesScrollDots', initSeriesScrollDots],
    ['initAdaptiveImagePriority', initAdaptiveImagePriority],
    ['initInteractionA11y', initInteractionA11y],
    ['injectUrlMetadata', injectUrlMetadata],
    ['injectStructuredData', injectStructuredData]
  ];

  initializers.forEach(([label, callback]) => safeInit(label, callback));
  await initPageModule();
});
