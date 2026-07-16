// Passive watcher for the REAL Site24x7 "Add Widget" config panel.
// Captures Resource Type / Widget(s) / Show / Time Period / Chart Type as
// the user naturally configures a widget — no automation, no clicking.

function getWidgetConfigSnapshot() {
  const resourceType = document.querySelector('#resourceTypes_dropdown_label')?.textContent.trim() || null;
  const widgetsEl = document.querySelector('#attributes_dropdown_label .selectmenu-label');
  const widgets = widgetsEl ? widgetsEl.textContent.trim() : null;
  const show = document.querySelector('#monitors_limit_dropdown_label')?.textContent.trim() || null;
  const timePeriodEl = document.querySelector(
    '#_dropdown_label, [id$="_dropdown_label"]:not(#resourceTypes_dropdown_label):not(#attributes_dropdown_label):not(#monitors_limit_dropdown_label)'
  );
  const timePeriod = timePeriodEl ? timePeriodEl.textContent.trim() : null;
  const checkedRadio = document.querySelector('input[name="chartType"]:checked');
  const chartType = checkedRadio ? checkedRadio.id : null; // e.g. "TimeChart", "AreaChart"

  return { resourceType, widgets, show, timePeriod, chartType, capturedAt: Date.now() };
}

let lastConfigSnapshot = null;

function maybeReportSnapshot() {
  const panel = document.querySelector('.widget-add-widget-body');
  if (!panel) return;
  const snapshot = getWidgetConfigSnapshot();
  const key = JSON.stringify(snapshot);
  if (key === lastConfigSnapshot) return;
  lastConfigSnapshot = key;

  console.log('[widget-config]', snapshot);

  // Local mirror of the whole snapshot (existing behavior, unchanged).
  fetch('http://127.0.0.1:8000/api/widget-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(snapshot)
  }).catch(() => {});

  // New: report just the combo fields for the "commonly used together"
  // aggregation. The backend itself filters out incomplete snapshots
  // (e.g. resourceType still "No items selected" or missing chartType),
  // so it's safe to fire this on every change without over-filtering here.
  fetch('http://127.0.0.1:8000/api/v1/widget-config-observations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chartType: snapshot.chartType,
      resourceType: snapshot.resourceType,
      show: snapshot.show,
      timePeriod: snapshot.timePeriod,
      capturedAt: snapshot.capturedAt
    })
  }).catch(() => {});
}

const configObserver = new MutationObserver(maybeReportSnapshot);

const panelWatcher = new MutationObserver(() => {
  const panel = document.querySelector('.widget-add-widget-body');
  if (panel && !panel.dataset.watcherAttached) {
    panel.dataset.watcherAttached = 'true';
    configObserver.observe(panel, { childList: true, subtree: true, characterData: true });
  }
});
panelWatcher.observe(document.body, { childList: true, subtree: true });


function slugifyForId(text) {
  return (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function scrapeWidgetCatalog() {
  const panel = document.querySelector('.left-form-body');
  if (!panel) return null;

  const categoryEls = panel.querySelectorAll(':scope > .category-item');
  const categories = [];

  categoryEls.forEach((catEl) => {
    const headingEl = catEl.querySelector('.category-heading');
    const categoryName = headingEl ? headingEl.textContent.trim() : null;
    if (!categoryName) return;

    const descEl = catEl.querySelector('.category-desc');
    const description = descEl ? descEl.textContent.trim() : null;

    const widgets = [];
    catEl.querySelectorAll('.widget-item').forEach((item) => {
      const txtEl = item.querySelector('.widget-category-txt');
      const typeLabel = txtEl ? (txtEl.getAttribute('title') || txtEl.textContent.trim()) : null;
      if (!typeLabel) return;
      // widget-item-live class and/or a <sup>Live</sup> badge both indicate
      // a live widget -- checking both since either could theoretically be
      // present without the other.
      const isLive = item.classList.contains('widget-item-live') || !!item.querySelector('sup');
      // The catalog widget ids (e.g. "widget-item-perf-timeseries") are
      // Site24x7's own stable catalog ids -- NOT per-account instance ids
      // like the ones dashboard-widget-sync.js captures off the live grid
      // -- so these are safe to use as-is and will actually match across
      // different accounts/orgs.
      const widgetItemId = item.id || `${slugifyForId(categoryName)}_${slugifyForId(typeLabel)}`;
      widgets.push({ widget_item_id: widgetItemId, type_label: typeLabel, is_live: isLive });
    });

    if (widgets.length) categories.push({ category: categoryName, description, widgets });
  });

  return categories.length ? categories : null;
}

let lastCatalogKey = null;

function maybeReportCatalog() {
  const categories = scrapeWidgetCatalog();
  if (!categories) {
    console.log('[widget-catalog] no matching panel/categories found on this page -- selectors likely need adjusting for the real markup. If you\'re on the Add Widget TYPE PICKER step and see this, copy the panel\'s outer HTML and send it over.');
    return;
  }
  const key = JSON.stringify(categories);
  if (key === lastCatalogKey) return;
  lastCatalogKey = key;

  console.log('[widget-catalog] captured', categories.length, 'categor(y/ies)', categories);

  fetch('http://127.0.0.1:8000/api/widget-catalog', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ categories }),
  })
    .then((res) => res.json())
    .then((data) => console.log('[widget-catalog] sent', data))
    .catch((err) => console.log('[widget-catalog] could not reach http://127.0.0.1:8000 — is your app running?', err));
}

const catalogObserver = new MutationObserver(() => {
  clearTimeout(window.__catalogDebounce);
  window.__catalogDebounce = setTimeout(maybeReportCatalog, 800);
});
catalogObserver.observe(document.body, { childList: true, subtree: true });