import {
  buildAbsoluteUrl,
  buildMediaShellAttributes,
  buildResponsiveImage,
  getAspectRatioValue,
  getPortfolioPath,
  getSeriesBySlug,
  getSeriesCover,
  getSeriesNeighbors,
  getSeriesPath,
  getSeriesWorks,
  getSortedSeries,
  getWorkOrientation,
  siteData
} from './data.js';
import {
  buildInquiryUrl,
  createShortlistButton,
  filterAccessibleSeries,
  hasSavedWork,
  isSeriesUnlocked,
  lockSeriesAccess,
  saveWork,
  syncShortlistButtons,
  toggleWork,
  unlockSeriesAccess
} from './collection-tools.js';

function currentSeries() {
  const params = new URLSearchParams(window.location.search);
  const ordered = getSortedSeries({ includePrivate: true });
  // Series pages live at /series/<slug>/ and name their series on <body>;
  // the old ?series= query still works on /series.html.
  const slug = params.get('series') || document.body.dataset.seriesSlug || '';
  return getSeriesBySlug(slug, { includePrivate: true }) || ordered[0] || null;
}

function ensureHeadElement(selector, tagName, attributes = {}) {
  let element = document.querySelector(selector);
  if (!element) {
    element = document.createElement(tagName);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    document.head.append(element);
  }
  return element;
}

function beginSeriesSwap() {
  document.documentElement.classList.add('series-query-loading');
}

function endSeriesSwap() {
  window.requestAnimationFrame(() => {
    document.documentElement.classList.remove('series-query-loading');
  });
}

function ensureSectionBefore(referenceSelector, className, dataName) {
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


function storyTypeLabel(series) {
  return series?.projectType === 'performance' ? 'Stage Work' : 'Series';
}

function summarizeStoryText(text, fallback = '', limit = 190) {
  const cleaned = String(text || fallback || '').replace(/\s+/g, ' ').trim();
  if (!cleaned) return '';
  if (cleaned.length <= limit) return cleaned;
  const clipped = cleaned.slice(0, limit).replace(/\s+\S*$/, '').replace(/[ ,;:.]+$/, '');
  return `${clipped}…`;
}

function normalizeLayoutToken(value, fallback = 'auto') {
  const aliases = {
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
  const allowed = new Set(['auto', 'quiet', 'standard', 'medium', 'large', 'wide', 'full']);
  const raw = String(value || '').trim().toLowerCase().replace(/_/g, '-');
  const token = aliases[raw] || raw || fallback;
  return allowed.has(token) ? token : fallback;
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

function getSeriesFrameLayout(series, work, index, total) {
  const override = getWorkLayoutToken(work, 'series', 'auto');
  if (override !== 'auto') return override;
  if (index === 0 || index === total - 1 || index % 5 === 0) return 'large';
  if (index === Math.floor(total / 2) || getWorkOrientation(work) === 'landscape') return 'medium';
  return 'standard';
}

function getSeriesImageSizes(layout) {
  return {
    quiet: '(min-width: 1100px) 24vw, (min-width: 760px) 42vw, 100vw',
    standard: '(min-width: 1100px) 29vw, (min-width: 760px) 48vw, 100vw',
    medium: '(min-width: 1100px) 38vw, (min-width: 760px) 58vw, 100vw',
    large: '(min-width: 1100px) 52vw, (min-width: 760px) 62vw, 100vw',
    wide: '(min-width: 1100px) 64vw, (min-width: 760px) 82vw, 100vw',
    full: '(min-width: 1100px) 78vw, (min-width: 760px) 92vw, 100vw'
  }[layout] || '(min-width: 1100px) 29vw, (min-width: 760px) 48vw, 100vw';
}

function sequenceRoleLabel(series, index, total) {
  if (total <= 1) return 'Single-image story';
  if (index === 0) return 'Opening image';
  if (index === total - 1) return 'Closing image';
  if (series?.projectType === 'performance') {
    if (index === Math.floor(total / 2)) return 'Turning point';
    return index < total / 2 ? 'Building pressure' : 'Aftermath';
  }
  if (index === Math.floor(total / 2)) return 'Pivot image';
  return index < total / 2 ? 'Middle movement' : 'Later movement';
}

function buildStoryMapMarkup(series, works) {
  if (!series || !works.length) return '';
  const first = works[0];
  const last = works[works.length - 1];
  const kind = storyTypeLabel(series);
  const summary = summarizeStoryText(
    series.cardSummary || series.description || series.mood,
    'This story is meant to be read through sequence rather than as a loose grid of images.',
    220
  );
  const sequenceNote = series.storySequenceText || (kind === 'Stage Work'
    ? 'This stage work keeps the pressure of the play intact: an opening threshold, a middle of accumulating tension, and a final image that decides what remains.'
    : 'This series is paced as a visual essay: the first image opens the threshold, the middle images deepen the pressure, and the ending image leaves the final residue.');
  const openingText = series.storyOpeningText || summarizeStoryText(first.caption || first.alt || first.location || first.year, '', 140) || 'The first image opens the threshold of the story.';
  const closingText = series.storyClosingText || summarizeStoryText(last.caption || last.alt || last.location || last.year, '', 140) || 'The final image keeps the last emotional residue of the story.';
  return `
    <div class="series-story-map__head">
      <div>
        <p class="eyebrow">How to read this story</p>
        <h2 class="section-title">${kind} in sequence</h2>
      </div>
      <p class="section-intro">${summary}</p>
    </div>
    <div class="series-story-map__grid">
      <article class="story-note">
        <p class="eyebrow">Opening</p>
        <h3>${first.title}</h3>
        <p>${openingText}</p>
      </article>
      <article class="story-note story-note--center">
        <p class="eyebrow">Sequence logic</p>
        <h3>${String(works.length).padStart(2, '0')} images · ${kind}</h3>
        <p>${sequenceNote}</p>
      </article>
      <article class="story-note">
        <p class="eyebrow">Ending</p>
        <h3>${last.title}</h3>
        <p>${closingText}</p>
      </article>
    </div>
  `;
}

function updateMeta(series, cover, works) {
  const pageTitle = `${series.title} - STILLMRK`;
  const description = `${series.title}. ${series.description}`;
  const pageUrl = new URL(getSeriesPath(series.slug), window.location.href).href;
  const coverImageUrl = buildAbsoluteUrl(cover.src);

  document.title = pageTitle;
  document.querySelector('meta[name="description"]')?.setAttribute('content', description);
  document.querySelector('meta[property="og:title"]')?.setAttribute('content', pageTitle);
  document.querySelector('meta[property="og:description"]')?.setAttribute('content', description);
  document.querySelector('meta[property="og:image"]')?.setAttribute('content', coverImageUrl);
  document.querySelector('meta[property="twitter:title"]')?.setAttribute('content', pageTitle);
  document.querySelector('meta[property="twitter:description"]')?.setAttribute('content', description);
  document.querySelector('meta[property="twitter:image"]')?.setAttribute('content', coverImageUrl);

  ensureHeadElement('meta[property="og:url"]', 'meta', { property: 'og:url' }).setAttribute('content', pageUrl);
  ensureHeadElement('link[rel="canonical"]', 'link', { rel: 'canonical' }).setAttribute('href', pageUrl);

  if (series.visibility === 'private') {
    ensureHeadElement('meta[name="robots"]', 'meta', { name: 'robots' }).setAttribute('content', 'noindex,nofollow,max-image-preview:large');
  }

  const schemaScript = document.querySelector('[data-page-schema]');
  if (!schemaScript) return;

  schemaScript.textContent = JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: pageTitle,
      description,
      url: pageUrl,
      image: coverImageUrl,
      about: {
        '@type': 'CreativeWorkSeries',
        name: series.title,
        description: series.description
      },
      hasPart: works.map((work) => ({
        '@type': 'ImageObject',
        name: work.title,
        description: work.alt,
        contentUrl: buildAbsoluteUrl(work.src),
        representativeOfPage: work.id === cover.id
      }))
    },
    null,
    2
  );
}

function renderDownloads(series) {
  const section = ensureSectionBefore('[data-related-series]', 'series-downloads panel panel--soft reveal', 'seriesDownloads');
  if (!section) return;
  const downloads = (siteData.downloads || []).filter((item) => (series.downloadIds || []).includes(item.id));
  if (!downloads.length) {
    section.remove();
    return;
  }

  section.innerHTML = `
    <div class="series-downloads__head">
      <p class="eyebrow">Downloads</p>
      <h2 class="section-title">Supporting material for this project.</h2>
      <p class="section-intro">Use these documents for press context, exhibition coordination, or curatorial review.</p>
    </div>
    <div class="download-grid">
      ${downloads
        .map(
          (item) => `
            <article class="download-card">
              <p class="eyebrow">${item.kind || 'Document'}</p>
              <h3>${item.title}</h3>
              <p>${item.description || ''}</p>
              <a class="button button--secondary" href="${item.file}" target="_blank" rel="noreferrer">Open document</a>
            </article>
          `
        )
        .join('')}
    </div>
  `;
}

function renderSeriesActions(series, works) {
  const actions = document.querySelector('.hero__actions');
  if (!actions) return;
  const savedCount = works.filter((work) => hasSavedWork(work.id)).length;
  const inquiryType = series.projectType === 'commissioned' ? 'Commission' : 'Print inquiry';
  actions.innerHTML = `
    <a class="button" data-series-portfolio-link href="${getPortfolioPath(series.slug)}">View ${series.title} in the portfolio grid</a>
    <a class="button button--secondary" href="${buildInquiryUrl({ seriesSlug: series.slug, workIds: works.map((work) => work.id), inquiryType })}">Inquire about this series</a>
    ${series.allowFavorites === false ? '' : `<button class="button button--ghost" type="button" data-save-series="${series.slug}">Save all ${works.length} works${savedCount ? ` · ${savedCount} already saved` : ''}</button>`}
    ${series.visibility === 'private' && isSeriesUnlocked(series) ? `<button class="button button--ghost" type="button" data-lock-series="${series.slug}">Lock private series</button>` : ''}
  `;
}

function renderSeriesIndex(series) {
  const index = document.querySelector('[data-series-index]');
  if (!index) return;
  const visibleSeries = filterAccessibleSeries(getSortedSeries({ includePrivate: true }).filter((item) => item.slug === series.slug || item.visibility !== 'private' || isSeriesUnlocked(item)));
  index.innerHTML = visibleSeries
    .map((item) => `
      <li>
        <a class="${item.slug === series.slug ? 'is-active' : ''}" href="${getSeriesPath(item.slug)}">
          <span class="series-index__label"><span>${item.title}</span>${storyTypeLabel(item) === 'Stage Work' ? '<em class="series-index__badge">Stage Work</em>' : ''}</span>
          <small>${String(getSeriesWorks(item.slug).length).padStart(2, '0')}</small>
        </a>
      </li>
    `)
    .join('');
}

function renderLockState(series, cover) {
  document.querySelector('[data-series-description]').textContent = series.accessNote || 'This project is restricted to invited reviewers.';
  document.querySelector('[data-series-count]').textContent = 'Private review archive';

  const hero = document.querySelector('[data-series-hero]');
  if (hero) {
    hero.innerHTML = `
      <div class="private-series-card">
        <p class="eyebrow">Restricted access</p>
        <h2>${series.clientName ? `${series.clientName} review` : 'Private series'}</h2>
        <p>${series.accessNote || 'Enter the access code shared with you to load the full sequence.'}</p>
        <form class="private-series-form" data-series-access-form>
          <label class="field">
            <span>Access code</span>
            <input type="password" name="accessCode" autocomplete="one-time-code" required>
          </label>
          <div class="private-series-form__actions">
            <button class="button" type="submit">Unlock series</button>
            <p class="form-note" data-series-access-status aria-live="polite">Access is checked in this browser only.</p>
          </div>
        </form>
      </div>
    `;
  }

  const gallery = document.querySelector('[data-series-gallery]');
  if (gallery) {
    gallery.innerHTML = `
      <article class="series-gate panel reveal">
        <p class="eyebrow">Client review mode</p>
        <h2>The sequence is hidden until the correct access code is entered.</h2>
        <p>This static build stores the unlock state in your current browser. It is suitable for local or provisional review only.</p>
      </article>
    `;
  }

  document.querySelector('[data-related-series]')?.replaceChildren();
  document.querySelector('[data-series-pagination]')?.replaceChildren();
  const downloadsSection = document.querySelector('[data-series-downloads]');
  downloadsSection?.remove();
  document.dispatchEvent(new CustomEvent('stillmrk:refresh'));
}

function renderSeriesPage() {
  beginSeriesSwap();
  const series = currentSeries();
  if (!series) {
    endSeriesSwap();
    return;
  }
  const works = getSeriesWorks(series.slug, { includePrivate: true });
  const cover = getSeriesCover(series) || works[0];
  const heroFigure = document.querySelector('[data-series-hero]');
  const configuredHeroId = series.heroWorkId || heroFigure?.getAttribute('data-series-default-hero-id') || siteData?.pages?.series?.heroWorkId || '';
  const configuredHero = configuredHeroId ? siteData.works.concat(siteData.reviewWorks || []).find((work) => work.id === configuredHeroId) : null;
  const heroWork = configuredHero || cover;
  const neighbors = getSeriesNeighbors(series.slug, { includePrivate: true });

  if (!heroWork) {
    endSeriesSwap();
    return;
  }

  updateMeta(series, heroWork, works);

  document.querySelector('[data-series-title]').textContent = series.title;
  const headingNode = document.querySelector('[data-series-heading]');
  if (headingNode) {
    headingNode.textContent = series.title;
  }
  document.querySelector('[data-series-years]').textContent = series.years;
  document.querySelector('[data-series-mood]').textContent = series.mood;
  document.querySelector('[data-series-count]').textContent = `${works.length} work${works.length === 1 ? '' : 's'}`;
  const descriptionNode = document.querySelector('[data-series-description]');
  if (descriptionNode) {
    const pageLead = descriptionNode.getAttribute('data-series-lead-prefix') || '';
    const seriesDescriptionHtml = String(series.descriptionHtml || '').trim();
    if (seriesDescriptionHtml) descriptionNode.innerHTML = seriesDescriptionHtml; // escaped at build time
    else descriptionNode.textContent = String(series.description || '').trim() || pageLead;
  }

  renderSeriesActions(series, works);
  renderSeriesIndex(series);

  const storyMap = document.querySelector('[data-series-story-map]');
  if (storyMap) {
    storyMap.innerHTML = buildStoryMapMarkup(series, works);
  }

  const portfolioLink = document.querySelector('[data-series-portfolio-link]');
  if (portfolioLink) {
    portfolioLink.href = getPortfolioPath(series.slug);
    portfolioLink.textContent = `View ${series.title} in the portfolio grid`;
  }

  if (series.visibility === 'private' && !isSeriesUnlocked(series)) {
    renderLockState(series, cover);
    endSeriesSwap();
    return;
  }

  const hero = document.querySelector('[data-series-hero]');
  hero.innerHTML = `
    <div class="series-masthead__visual" style="--media-ratio: ${getAspectRatioValue(heroWork, 'cover')};">
      ${buildResponsiveImage(heroWork, {
      sizes: '(min-width: 1100px) 46vw, (min-width: 760px) 56vw, 100vw',
      loading: 'eager',
      fetchpriority: 'high'
    })}
    </div>
    <figcaption class="media-caption"><small>${heroWork.caption || `${heroWork.title} / ${heroWork.location} / ${heroWork.year}`}</small></figcaption>
  `;

  const gallery = document.querySelector('[data-series-gallery]');
  if (gallery) {
    gallery.innerHTML = works
      .map((work, index) => {
        const orientation = getWorkOrientation(work);
        const layout = getSeriesFrameLayout(series, work, index, works.length);
        const large = ['large', 'wide', 'full'].includes(layout);
        const roleLabel = sequenceRoleLabel(series, index, works.length);
        const roleClass = index === 0 ? 'series-frame--opening' : index === works.length - 1 ? 'series-frame--closing' : index === Math.floor(works.length / 2) ? 'series-frame--turning' : '';
        const serviceLine = [work.printAvailable ? 'Prints available' : '', work.licensingAvailable ? 'Licensing available' : '', work.priceNote || '']
          .filter(Boolean)
          .join(' · ');
        const frameText = work.caption || work.alt || work.year || '';
        const isPriorityFrame = index < 2;

        return `
          <article class="series-frame reveal series-frame--${orientation} ${large ? 'series-frame--featured' : ''} ${roleClass} series-frame--layout-${layout}" data-layout="${layout}" data-sequence-role="${roleLabel.toLowerCase()}">
            <figure
              ${buildMediaShellAttributes(work, { className: 'series-frame__media', context: 'series' })}
              ${isPriorityFrame ? '' : 'data-priority-candidate="series"'}>
              ${buildResponsiveImage(work, {
                sizes: getSeriesImageSizes(layout),
                loading: isPriorityFrame ? 'eager' : 'lazy',
                fetchpriority: isPriorityFrame ? 'high' : 'auto'
              })}
            </figure>
            <div class="series-frame__body">
              <p class="series-frame__eyebrow">${roleLabel}</p>
              <div class="series-frame__meta">
                <span>${String(index + 1).padStart(2, '0')}</span>
                <span>${work.location}</span>
                <span>${storyTypeLabel(series)}</span>
              </div>
              <h2>${work.title}</h2>
              <p>${frameText}</p>
              <div class="series-frame__actions">
                ${series.allowFavorites === false ? '' : createShortlistButton(work.id, { className: 'save-chip--soft' }).outerHTML}
                ${series.allowInquiryBasket === false ? '' : `<a class="text-link" href="${buildInquiryUrl({ workIds: [work.id], seriesSlug: series.slug, inquiryType: work.printAvailable ? 'Print inquiry' : 'Editorial licensing' })}">Inquire</a>`}
              </div>
              ${serviceLine ? `<p class="series-frame__service">${serviceLine}</p>` : ''}
            </div>
          </article>
        `;
      })
      .join('');
  }

  renderDownloads(series);

  const related = document.querySelector('[data-related-series]');
  if (related) {
    related.innerHTML = filterAccessibleSeries(getSortedSeries())
      .filter((item) => item.slug !== series.slug)
      .slice(0, 3)
      .map((item) => {
        const work = getSeriesCover(item);
        if (!work) return '';
        return `
          <article class="series-card panel reveal">
            <a ${buildMediaShellAttributes(work, { className: 'series-card__media', context: 'cover' })} href="${getSeriesPath(item.slug)}">
              ${buildResponsiveImage(work, {
                sizes: '(min-width: 1100px) 28vw, (min-width: 760px) 48vw, 100vw',
                loading: 'lazy',
                fetchpriority: 'auto'
              })}
            </a>
            <div class="series-card__body">
              <div class="series-card__meta">
                <span>${storyTypeLabel(item)}</span>
                <span>${String(getSeriesWorks(item.slug).length).padStart(2, '0')} works</span>
              </div>
              <h3>${item.title}</h3>
              <p>${summarizeStoryText(item.description || item.mood, item.mood, 150)}</p>
              <div class="series-card__footer">
                <span>${item.years}</span>
                <a href="${getSeriesPath(item.slug)}">Open story</a>
              </div>
            </div>
          </article>
        `;
      })
      .join('');
  }

  const pagination = document.querySelector('[data-series-pagination]');
  if (pagination) {
    const links = [];
    if (neighbors.previous && isSeriesUnlocked(neighbors.previous)) {
      links.push(`
        <a class="pagination-link panel panel--soft" href="${getSeriesPath(neighbors.previous.slug)}">
          <span>Previous series</span>
          <strong>${neighbors.previous.title}</strong>
        </a>
      `);
    }
    if (neighbors.next && isSeriesUnlocked(neighbors.next)) {
      links.push(`
        <a class="pagination-link pagination-link--next panel panel--soft" href="${getSeriesPath(neighbors.next.slug)}">
          <span>Next series</span>
          <strong>${neighbors.next.title}</strong>
        </a>
      `);
    }
    pagination.innerHTML = links.join('');
  }

  syncShortlistButtons(document);
  document.dispatchEvent(new CustomEvent('stillmrk:refresh'));
  endSeriesSwap();
}

document.addEventListener('click', (event) => {
  const saveButton = event.target.closest('[data-save-work]');
  if (saveButton) {
    event.preventDefault();
    toggleWork(saveButton.dataset.saveWork || '');
    syncShortlistButtons(document);
    return;
  }

  const saveSeries = event.target.closest('[data-save-series]');
  if (saveSeries) {
    event.preventDefault();
    const series = getSeriesBySlug(saveSeries.dataset.saveSeries || '', { includePrivate: true });
    if (!series) return;
    getSeriesWorks(series.slug, { includePrivate: true }).forEach((work) => saveWork(work.id));
    syncShortlistButtons(document);
    renderSeriesPage();
    return;
  }

  const lockSeries = event.target.closest('[data-lock-series]');
  if (lockSeries) {
    event.preventDefault();
    lockSeriesAccess(lockSeries.dataset.lockSeries || '');
    renderSeriesPage();
  }
});

document.addEventListener('submit', async (event) => {
  const form = event.target.closest('[data-series-access-form]');
  if (!form) return;
  event.preventDefault();
  const series = currentSeries();
  const status = form.querySelector('[data-series-access-status]');
  const code = new FormData(form).get('accessCode');
  status.textContent = 'Checking access code…';
  const result = await unlockSeriesAccess(series, String(code || ''));
  if (!result.ok) {
    status.textContent = 'The access code was not accepted. Check the shared code and try again.';
    return;
  }
  status.textContent = 'Access granted. Loading the sequence…';
  renderSeriesPage();
});

window.addEventListener('stillmrk:shortlist-change', () => syncShortlistButtons(document));
window.addEventListener('stillmrk:series-unlock', () => renderSeriesPage());
window.addEventListener('stillmrk:series-lock', () => renderSeriesPage());

const requestedSeriesSlug = new URLSearchParams(window.location.search).get('series');
const hasServerRenderedState = Boolean(document.querySelector('[data-series-hero]')?.children.length)
  && Boolean(document.querySelector('[data-series-index]')?.children.length)
  && Boolean(document.querySelector('[data-series-gallery]')?.children.length);

if (requestedSeriesSlug || !hasServerRenderedState) {
  renderSeriesPage();
} else {
  syncShortlistButtons(document);
  endSeriesSwap();
}
