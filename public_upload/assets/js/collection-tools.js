import { getSeriesBySlug, getWorkById } from './data.js';

const SHORTLIST_KEY = 'stillmrk-shortlist-v1';
const ACCESS_KEY = 'stillmrk-series-access-v1';

function readJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const value = JSON.parse(raw);
    return value && typeof value === 'object' ? value : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures in private browsing or quota-restricted modes.
  }
}

function emit(name, detail = {}) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

export function getSavedWorkIds() {
  const payload = readJson(SHORTLIST_KEY, { ids: [] });
  return Array.isArray(payload.ids) ? payload.ids.filter((id) => typeof id === 'string' && id.trim()) : [];
}

export function hasSavedWork(workId) {
  return getSavedWorkIds().includes(workId);
}

export function saveWork(workId) {
  const ids = new Set(getSavedWorkIds());
  ids.add(workId);
  writeJson(SHORTLIST_KEY, { ids: [...ids] });
  emit('stillmrk:shortlist-change', { ids: [...ids] });
  return [...ids];
}

export function removeWork(workId) {
  const ids = new Set(getSavedWorkIds());
  ids.delete(workId);
  writeJson(SHORTLIST_KEY, { ids: [...ids] });
  emit('stillmrk:shortlist-change', { ids: [...ids] });
  return [...ids];
}

export function toggleWork(workId) {
  return hasSavedWork(workId) ? removeWork(workId) : saveWork(workId);
}

export function clearSavedWorks() {
  writeJson(SHORTLIST_KEY, { ids: [] });
  emit('stillmrk:shortlist-change', { ids: [] });
}

export function getSavedWorks() {
  return getSavedWorkIds().map((id) => getWorkById(id)).filter(Boolean);
}

export function getUnlockedSeriesMap() {
  const payload = readJson(ACCESS_KEY, { series: {} });
  return payload.series && typeof payload.series === 'object' ? payload.series : {};
}

export function isSeriesUnlocked(slug) {
  const series = typeof slug === 'string' ? getSeriesBySlug(slug) : slug;
  if (!series) return false;
  if ((series.visibility || 'public') !== 'private') return true;
  const unlocked = getUnlockedSeriesMap();
  return unlocked[series.slug] === series.accessHash;
}

async function sha256(value) {
  const input = new TextEncoder().encode(value);
  const digest = await window.crypto.subtle.digest('SHA-256', input);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function unlockSeriesAccess(series, code) {
  if (!series || (series.visibility || 'public') !== 'private') return { ok: true, reason: 'public' };
  const candidate = String(code || '').trim();
  if (!candidate) return { ok: false, reason: 'missing' };
  const hash = await sha256(candidate);
  if (hash !== series.accessHash) return { ok: false, reason: 'mismatch' };
  const unlocked = getUnlockedSeriesMap();
  unlocked[series.slug] = series.accessHash;
  writeJson(ACCESS_KEY, { series: unlocked });
  emit('stillmrk:series-unlock', { slug: series.slug });
  return { ok: true, reason: 'matched' };
}

export function lockSeriesAccess(slug) {
  const unlocked = getUnlockedSeriesMap();
  delete unlocked[slug];
  writeJson(ACCESS_KEY, { series: unlocked });
  emit('stillmrk:series-lock', { slug });
}

export function buildInquiryUrl({ workIds = [], seriesSlug = '', inquiryType = '' } = {}) {
  const url = new URL('contact.html', window.location.href);
  const ids = workIds.filter(Boolean);
  if (ids.length) url.searchParams.set('works', ids.join(','));
  if (seriesSlug) url.searchParams.set('series', seriesSlug);
  if (inquiryType) url.searchParams.set('inquiryType', inquiryType);
  if (!ids.length && !seriesSlug) url.searchParams.set('useShortlist', '1');
  return `${url.pathname}${url.search}`;
}

export function filterAccessibleSeries(seriesList) {
  return seriesList.filter((series) => isSeriesUnlocked(series));
}

export function filterAccessibleWorks(works) {
  return works.filter((work) => isSeriesUnlocked(work.series));
}

export function createShortlistButton(workId, { className = '', label = 'Save', savedLabel = 'Saved' } = {}) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `save-chip ${className}`.trim();
  button.dataset.saveWork = workId;
  button.setAttribute('aria-pressed', String(hasSavedWork(workId)));
  button.innerHTML = `<span>${hasSavedWork(workId) ? savedLabel : label}</span>`;
  return button;
}

export function syncShortlistButtons(root = document) {
  root.querySelectorAll('[data-save-work]').forEach((button) => {
    const workId = button.dataset.saveWork;
    const saved = hasSavedWork(workId);
    button.classList.toggle('is-saved', saved);
    button.setAttribute('aria-pressed', String(saved));
    const span = button.querySelector('span');
    if (span) span.textContent = saved ? 'Saved' : 'Save';
  });

  root.querySelectorAll('[data-shortlist-count]').forEach((node) => {
    node.textContent = String(getSavedWorkIds().length).padStart(2, '0');
  });

  root.querySelectorAll('[data-shortlist-empty-toggle]').forEach((node) => {
    const empty = getSavedWorkIds().length === 0;
    node.toggleAttribute('disabled', empty);
    if (node instanceof HTMLElement) node.hidden = empty && node.dataset.keepVisible !== 'true';
  });
}
