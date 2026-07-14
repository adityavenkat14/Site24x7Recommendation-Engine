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
  fetch('http://localhost:8000/api/widget-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(snapshot)
  }).catch(() => {});

  // New: report just the combo fields for the "commonly used together"
  // aggregation. The backend itself filters out incomplete snapshots
  // (e.g. resourceType still "No items selected" or missing chartType),
  // so it's safe to fire this on every change without over-filtering here.
  fetch('http://localhost:8000/api/v1/widget-config-observations', {
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