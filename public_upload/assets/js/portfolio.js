import {
  buildMediaShellAttributes,
  buildResponsiveImage,
  getPortfolioWorks,
  getSeriesBySlug,
  getSeriesPath,
  getSortedSeries,
  getWorkOrientation
} from './data.js';
import {
  buildInquiryUrl,
  clearSavedWorks,
  createShortlistButton,
  filterAccessibleSeries,
  filterAccessibleWorks,
  getSavedWorkIds,
  hasSavedWork,
  syncShortlistButtons,
  toggleWork
} from './collection-tools.js';

const params = new URLSearchParams(window.location.search);
const allWorks = getPortfolioWorks();
const allSeries = getSortedSeries();
const requestedWorkId = params.get('work') || '';
let activeSeries = params.get('series') || 'all';
let searchTerm = params.get('search') || '';
let sortMode = params.get('sort') || 'curated';
let viewMode = params.get('view') === 'shortlist' ? 'shortlist' : 'all';
let searchDebounce;
const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });
const seriesMap = new Map(allSeries.map((series) => [series.slug, series]));

const filterRow = document.querySelector('[data-filter-row]');
const workGrid = document.querySelector('[data-work-grid]');
const workCount = document.querySelector('[data-work-count]');
const searchInput = document.querySelector('[data-portfolio-search]');
const sortSelect = document.querySelector('[data-portfolio-sort]');
const clearSearchButton = document.querySelector('[data-portfolio-clear]');
const resetButton = document.querySelector('[data-portfolio-reset]');
const toolsPanel = document.querySelector('.portfolio-tools');

function getAccessibleWorks() {
  return filterAccessibleWorks(allWorks);
}

function getAccessibleSeries() {
  return filterAccessibleSeries(allSeries);
}

const LAYOUT_TOKENS = new Set(['auto', 'quiet', 'standard', 'medium', 'large', 'wide', 'full']);
const LAYOUT_ALIASES = {
  small: 'quiet',
  compact: 'quiet',
  normal: 'standard',
  default: 'standard',
  regular: 'standard',
  feature: 'large',
  featured: 'large',
  hero: 'wide',
  cinematic: 'wide',
  span: 'wide'
};

function normalizeLayoutToken(value, fallback = 'auto') {
  const raw = String(value || '').trim().toLowerCase().replace(/_/g, '-');
  const token = LAYOUT_ALIASES[raw] || raw || fallback;
  return LAYOUT_TOKENS.has(token) ? token : fallback;
}

function getWorkLayoutToken(work, context, fallback = 'auto') {
  const direct = context === 'portfolio' ? work.portfolioLayout : work.seriesLayout;
  const directToken = normalizeLayoutToken(direct, 'auto');
  if (directToken !== 'auto') return directToken;

  const nested = work.displayLayouts && typeof work.displayLayouts === 'object'
    ? normalizeLayoutToken(work.displayLayouts[context], 'auto')
    : 'auto';

  return nested !== 'auto' ? nested : fallback;
}

function getPortfolioCardVariant(index, total, work = null) {
  const override = work ? getWorkLayoutToken(work, 'portfolio', 'auto') : 'auto';
  if (override !== 'auto') return override;

  if (index === 0) return 'lead';
  if (index === 1) return 'accent';
  if (total <= 2) return 'standard';

  const remaining = Math.max(total - 2, 0);
  const relativeIndex = Math.max(index - 2, 0);
  const fullRows = Math.floor(remaining / 3);
  const remainder = remaining % 3;
  const cutoff = fullRows * 3;

  if (relativeIndex < cutoff) return 'standard';
  if (remainder === 1) return 'standard';
  if (remainder === 2) return 'twin';
  return 'standard';
}

function getPortfolioLayoutClass(variant) {
  const canonical = normalizeLayoutToken({
    lead: 'large',
    accent: 'large',
    twin: 'standard'
  }[variant] || variant, 'standard');
  return `work-card--layout-${canonical}`;
}

function getPortfolioImageSizes(variant) {
  return {
    quiet: '(min-width: 1180px) 24vw, (min-width: 760px) 46vw, 100vw',
    standard: '(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw',
    medium: '(min-width: 1180px) 38vw, (min-width: 760px) 92vw, 100vw',
    large: '(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw',
    wide: '(min-width: 1180px) 62vw, (min-width: 760px) 92vw, 100vw',
    full: '(min-width: 1180px) 92vw, (min-width: 760px) 100vw, 100vw',
    lead: '(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw',
    accent: '(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw',
    twin: '(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw'
  }[variant] || '(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw';
}

function getPortfolioSummary(work, series, variant) {
  const caption = (work.caption || '').trim();
  if (caption) return caption;
  const seriesTitle = series?.title || 'Series';
  const fragments = [];
  if (variant === 'lead') fragments.push('Featured work');
  if (variant === 'accent') fragments.push(seriesTitle, work.location, work.year);
  else fragments.push(seriesTitle, work.location);
  if (work.projectType && work.projectType !== 'fine-art') fragments.push(work.projectType.replace('-', ' '));
  if (work.printAvailable) fragments.push('Print-ready');
  return [...new Set(fragments.filter(Boolean))].join(' · ');
}

function updateUrl() {
  const url = new URL(window.location.href);

  if (activeSeries === 'all') url.searchParams.delete('series');
  else url.searchParams.set('series', activeSeries);

  if (!searchTerm) url.searchParams.delete('search');
  else url.searchParams.set('search', searchTerm);

  if (sortMode === 'curated') url.searchParams.delete('sort');
  else url.searchParams.set('sort', sortMode);

  if (viewMode === 'shortlist') url.searchParams.set('view', 'shortlist');
  else url.searchParams.delete('view');

  window.history.replaceState({}, '', url);
}

function setClearButtonState() {
  if (!clearSearchButton) return;
  clearSearchButton.hidden = !searchTerm;
  clearSearchButton.disabled = !searchTerm;
}

function renderShortlistToolbar() {
  if (!toolsPanel) return;
  let bar = toolsPanel.querySelector('[data-shortlist-toolbar]');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'portfolio-shortlist-bar';
    bar.dataset.shortlistToolbar = 'true';
    toolsPanel.append(bar);
  }

  const savedIds = getSavedWorkIds();
  const inquiryHref = buildInquiryUrl({ workIds: savedIds, inquiryType: 'Print inquiry' });

  bar.innerHTML = `
    <div class="portfolio-shortlist-bar__copy">
      <span class="eyebrow">Shortlist</span>
      <strong><span data-shortlist-count>${String(savedIds.length).padStart(2, '0')}</span> saved works</strong>
      <p>Collect frames for print, licensing, or editorial review without losing your place in the archive.</p>
    </div>
    <div class="portfolio-shortlist-bar__actions">
      <button class="button button--secondary" type="button" data-view-shortlist aria-pressed="${String(viewMode === 'shortlist')}">${viewMode === 'shortlist' ? 'Viewing shortlist' : 'View shortlist'}</button>
      <button class="button button--ghost" type="button" data-clear-shortlist data-shortlist-empty-toggle>Clear saved</button>
      <a class="button" data-shortlist-inquiry data-shortlist-empty-toggle href="${inquiryHref}">Inquire about shortlist</a>
    </div>
  `;

  syncShortlistButtons(toolsPanel);
}

function renderFilters() {
  if (!filterRow) return;

  const accessibleWorks = getAccessibleWorks();
  const filters = [
    { value: 'all', label: 'All works', count: accessibleWorks.length },
    ...getAccessibleSeries().map((series) => ({
      value: series.slug,
      label: series.title,
      count: accessibleWorks.filter((work) => work.series === series.slug).length
    }))
  ];

  if (activeSeries !== 'all' && !filters.some((filter) => filter.value === activeSeries)) {
    activeSeries = 'all';
  }

  filterRow.innerHTML = filters
    .map(
      (filter) => `
        <button
          class="filter-chip ${activeSeries === filter.value ? 'is-active' : ''}"
          type="button"
          data-filter="${filter.value}"
          aria-pressed="${String(activeSeries === filter.value)}">
          <span>${filter.label}</span>
          <small>${String(filter.count).padStart(2, '0')}</small>
        </button>
      `
    )
    .join('');
}

function getFilteredWorks() {
  const normalizedSearch = searchTerm.trim().toLowerCase();
  const savedIds = new Set(getSavedWorkIds());
  const accessibleWorks = getAccessibleWorks();
  const requestedWork = accessibleWorks.find((work) => work.id === requestedWorkId);

  const works = accessibleWorks.filter((work) => {
    const series = seriesMap.get(work.series);
    const matchesSeries = activeSeries === 'all' || work.series === activeSeries;
    const matchesView = viewMode !== 'shortlist' || savedIds.has(work.id);
    if (!matchesSeries || !matchesView) return false;

    if (!normalizedSearch) return true;

    const searchText = [
      work.title,
      work.location,
      work.year,
      work.alt,
      work.medium || '',
      work.projectType || '',
      series?.title || '',
      series?.mood || ''
    ]
      .join(' ')
      .toLowerCase();

    return searchText.includes(normalizedSearch);
  });

  works.sort((a, b) => {
    if (requestedWork) {
      if (a.id === requestedWork.id) return -1;
      if (b.id === requestedWork.id) return 1;
    }
    if (sortMode === 'title') return collator.compare(a.title, b.title);
    if (sortMode === 'series') {
      return collator.compare(seriesMap.get(a.series)?.title || '', seriesMap.get(b.series)?.title || '') || collator.compare(a.title, b.title);
    }
    if (sortMode === 'location') return collator.compare(a.location, b.location) || collator.compare(a.title, b.title);
    return (a.portfolioOrder || 9999) - (b.portfolioOrder || 9999);
  });

  return works;
}

function renderSummary(works) {
  if (!workCount) return;

  const seriesLabel = activeSeries === 'all' ? 'All accessible series' : getSeriesBySlug(activeSeries)?.title || 'Selected series';
  const sortLabel = {
    curated: 'Curated order',
    title: 'Sorted by title',
    series: 'Sorted by series',
    location: 'Sorted by location'
  }[sortMode] || 'Curated order';

  const searchLabel = searchTerm ? ` · Search: “${searchTerm}”` : '';
  const shortlistLabel = viewMode === 'shortlist' ? ' · Saved shortlist only' : '';
  workCount.textContent = `${works.length} work${works.length === 1 ? '' : 's'} · ${seriesLabel} · ${sortLabel}${shortlistLabel}${searchLabel}`;

  if (resetButton) {
    const hasActiveFilters = activeSeries !== 'all' || Boolean(searchTerm) || sortMode !== 'curated' || viewMode === 'shortlist';
    resetButton.hidden = !hasActiveFilters;
    resetButton.disabled = !hasActiveFilters;
  }
}

function renderEmptyState() {
  if (!workGrid) return;

  const emptyMessage = viewMode === 'shortlist'
    ? 'Your shortlist is empty. Save works from the archive to bring them into a tighter review list.'
    : 'Broaden the search or return to the full portfolio.';

  workGrid.innerHTML = `
    <article class="empty-state panel reveal">
      <p class="eyebrow">No result</p>
      <h2>${viewMode === 'shortlist' ? 'No saved works yet.' : 'Nothing matches the current filter.'}</h2>
      <p>${emptyMessage}</p>
      <button class="button button--secondary" type="button" data-reset-filters>Reset filters</button>
    </article>
  `;

  document.dispatchEvent(new CustomEvent('stillmrk:refresh'));
}

function buildWorkActions(work, series) {
  const inquiryHref = buildInquiryUrl({ workIds: [work.id], seriesSlug: series?.slug || work.series, inquiryType: work.printAvailable ? 'Print inquiry' : 'Editorial licensing' });
  const priceNote = work.priceNote ? `<span class="work-card__note">${work.priceNote}</span>` : '';
  const availability = work.printAvailable || work.licensingAvailable
    ? `<span class="work-card__availability">${[work.printAvailable ? 'Prints' : '', work.licensingAvailable ? 'Licensing' : ''].filter(Boolean).join(' · ')}</span>`
    : '';

  return `
    <div class="work-card__actions">
      <button class="save-chip ${hasSavedWork(work.id) ? 'is-saved' : ''}" type="button" data-save-work="${work.id}" aria-pressed="${String(hasSavedWork(work.id))}"><span>${hasSavedWork(work.id) ? 'Saved' : 'Save'}</span></button>
      <a class="text-link" href="${inquiryHref}">Inquire</a>
    </div>
    ${availability || priceNote ? `<div class="work-card__service-row">${availability}${priceNote}</div>` : ''}
  `;
}

function renderGrid() {
  if (!workGrid) return;

  const works = getFilteredWorks();
  renderSummary(works);
  setClearButtonState();
  renderShortlistToolbar();

  if (!works.length) {
    renderEmptyState();
    return;
  }

  workGrid.innerHTML = works
    .map((work, index) => {
      const series = seriesMap.get(work.series);
      const orientation = getWorkOrientation(work);
      const variant = getPortfolioCardVariant(index, works.length, work);
      const imageSizes = getPortfolioImageSizes(variant);
      const summary = getPortfolioSummary(work, series, variant);
      const isPriorityCard = index < 2 || variant === 'lead';
      const priorityCandidateAttr = isPriorityCard ? '' : 'data-priority-candidate="portfolio"';
      const projectLabel = work.projectType && work.projectType !== 'fine-art' ? `<span>${work.projectType.replace('-', ' ')}</span>` : '';

      return `
        <article class="work-card panel reveal work-card--${orientation} work-card--${variant} ${getPortfolioLayoutClass(variant)}" data-work-id="${work.id}" data-layout="${variant}">
          <figure
            ${buildMediaShellAttributes(work, { className: 'work-card__media', context: 'portfolio' })}
            ${priorityCandidateAttr}>
            ${buildResponsiveImage(work, {
              sizes: imageSizes,
              loading: isPriorityCard ? 'eager' : 'lazy',
              fetchpriority: isPriorityCard ? 'high' : 'auto'
            })}
          </figure>
          <div class="work-card__body">
            <div class="work-card__meta">
              <span>${series?.title || 'Series'}</span>
              <span>${work.location}</span>
              ${projectLabel}
            </div>
            <h2 class="work-card__title">${work.title}</h2>
            <p>${summary}</p>
            <div class="work-card__footer">
              <span>${work.year}</span>
              <a href="${getSeriesPath(work.series)}">Open series</a>
            </div>
            ${buildWorkActions(work, series)}
          </div>
        </article>
      `;
    })
    .join('');

  syncShortlistButtons(workGrid);
  document.dispatchEvent(new CustomEvent('stillmrk:refresh'));
}

function resetFilters() {
  activeSeries = 'all';
  searchTerm = '';
  sortMode = 'curated';
  viewMode = 'all';

  if (searchInput) searchInput.value = '';
  if (sortSelect) sortSelect.value = 'curated';

  renderFilters();
  renderGrid();
  updateUrl();
}

filterRow?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-filter]');
  if (!button) return;
  event.preventDefault();
  activeSeries = button.dataset.filter;
  renderFilters();
  renderGrid();
  updateUrl();
});

workGrid?.addEventListener('click', (event) => {
  if (event.target.closest('[data-reset-filters]')) {
    resetFilters();
    return;
  }

  const saveButton = event.target.closest('[data-save-work]');
  if (!saveButton) return;
  event.preventDefault();
  toggleWork(saveButton.dataset.saveWork || '');
  syncShortlistButtons(document);
  if (viewMode === 'shortlist') renderGrid();
});

searchInput?.addEventListener('input', () => {
  window.clearTimeout(searchDebounce);
  searchDebounce = window.setTimeout(() => {
    searchTerm = searchInput.value.trim();
    renderGrid();
    updateUrl();
  }, 120);
});

clearSearchButton?.addEventListener('click', () => {
  if (!searchInput) return;
  searchInput.value = '';
  searchTerm = '';
  setClearButtonState();
  renderGrid();
  updateUrl();
  searchInput.focus();
});

resetButton?.addEventListener('click', resetFilters);

sortSelect?.addEventListener('change', () => {
  sortMode = sortSelect.value;
  renderGrid();
  updateUrl();
});

toolsPanel?.addEventListener('click', (event) => {
  const shortlistToggle = event.target.closest('[data-view-shortlist]');
  if (shortlistToggle) {
    event.preventDefault();
    viewMode = viewMode === 'shortlist' ? 'all' : 'shortlist';
    renderGrid();
    updateUrl();
    return;
  }

  const clear = event.target.closest('[data-clear-shortlist]');
  if (clear) {
    event.preventDefault();
    clearSavedWorks();
    renderGrid();
  }
});

window.addEventListener('stillmrk:shortlist-change', () => {
  syncShortlistButtons(document);
  if (viewMode === 'shortlist') renderGrid();
  else renderShortlistToolbar();
});

const hasQueryState = params.has('series') || params.has('search') || params.has('sort') || params.get('view') === 'shortlist';
const hasServerRenderedState = Boolean(filterRow?.children.length) && Boolean(workGrid?.children.length);

if (searchInput) searchInput.value = searchTerm;
if (sortSelect) sortSelect.value = sortMode;

if (hasQueryState || !hasServerRenderedState) {
  renderFilters();
  renderGrid();
  updateUrl();
} else {
  renderShortlistToolbar();
  syncShortlistButtons(document);
}
