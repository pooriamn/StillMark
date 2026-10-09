/*
  Consent-first analytics for STILLMRK.

  Google Analytics never loads until the visitor chooses "Accept". The choice is
  stored in this browser only and can be changed from "Cookie settings" in the
  footer. The analytics ID comes from <meta name="stillmark-analytics">, which
  the build emits only when content/site.yaml sets analytics_id.
*/
(function () {
  'use strict';

  var STORAGE_KEY = 'stillmark:consent';
  var meta = document.querySelector('meta[name="stillmark-analytics"]');
  var analyticsId = meta ? String(meta.getAttribute('content') || '').trim() : '';
  if (!/^G-[A-Z0-9]+$/i.test(analyticsId)) return;

  var loaded = false;
  var banner = null;

  function readChoice() {
    try { return window.localStorage.getItem(STORAGE_KEY); } catch (error) { return null; }
  }

  function writeChoice(value) {
    try { window.localStorage.setItem(STORAGE_KEY, value); } catch (error) { /* private mode: ask again next visit */ }
  }

  function clearAnalyticsCookies() {
    document.cookie.split(';').forEach(function (cookie) {
      var name = cookie.split('=')[0].trim();
      if (name === '_ga' || name.indexOf('_ga_') === 0 || name === '_gid') {
        var expires = '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
        document.cookie = name + expires;
        document.cookie = name + expires + '; domain=' + window.location.hostname;
        document.cookie = name + expires + '; domain=.' + window.location.hostname.replace(/^www\./, '');
      }
    });
  }

  function loadAnalytics() {
    if (loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', analyticsId);
    var script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(analyticsId);
    document.head.appendChild(script);
  }

  function hideBanner() {
    if (!banner) return;
    banner.hidden = true;
  }

  function decide(value) {
    var previous = readChoice();
    writeChoice(value);
    hideBanner();
    if (value === 'granted') {
      loadAnalytics();
    } else if (previous === 'granted') {
      // Analytics already ran on this page; clear its cookies and reload so
      // nothing keeps tracking after the visitor withdrew consent.
      clearAnalyticsCookies();
      window.location.reload();
    }
  }

  function buildBanner() {
    var element = document.createElement('section');
    element.className = 'consent-banner';
    element.setAttribute('role', 'region');
    element.setAttribute('aria-label', 'Cookie consent');
    element.hidden = true;
    element.innerHTML =
      '<p class="consent-banner__text">May this site use Google Analytics cookies to count visits? ' +
      'Nothing is shared for advertising, and the site works the same either way.</p>' +
      '<div class="consent-banner__actions">' +
      '<button type="button" class="button button--secondary" data-consent-choice="denied">Decline</button>' +
      '<button type="button" class="button" data-consent-choice="granted">Accept</button>' +
      '</div>';
    element.addEventListener('click', function (event) {
      var button = event.target.closest('[data-consent-choice]');
      if (button) decide(button.getAttribute('data-consent-choice'));
    });
    document.body.appendChild(element);
    return element;
  }

  function showBanner() {
    banner = banner || buildBanner();
    banner.hidden = false;
    var focusTarget = banner.querySelector('[data-consent-choice="granted"]');
    if (focusTarget && document.activeElement && document.activeElement.hasAttribute('data-consent-settings')) {
      focusTarget.focus();
    }
  }

  function init() {
    document.addEventListener('click', function (event) {
      if (event.target.closest('[data-consent-settings]')) showBanner();
    });
    var choice = readChoice();
    if (choice === 'granted') loadAnalytics();
    else if (choice !== 'denied') showBanner();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
