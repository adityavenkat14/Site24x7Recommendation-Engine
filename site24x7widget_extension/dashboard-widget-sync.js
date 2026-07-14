// Guard against duplicate injection: if the extension gets reloaded
// while this tab is already open, Chrome can re-run this content
// script into the SAME page context that still has the previous
// run's top-level variables alive, causing a
// "Identifier ... has already been declared" crash. Wrapping
// everything in this guard + IIFE means a second injection is a
// harmless no-op instead of a syntax error.
if (!window.__s247WidgetSyncLoaded) {
  window.__s247WidgetSyncLoaded = true;
  (function () {

  // Passive watcher for the Site24x7 DASHBOARD GRID (not the Add Widget
  // panel -- that's content.js, a separate file). Reads whichever widgets
  // are already placed on the dashboard you're currently viewing and
  // reports the whole set to your local app, so a dashboard -- new or
  // existing -- shows up in the app without needing to open the Add Widget
  // panel on it at all.
  //
  // Selectors below are verified against real captured markup from a
  // "Website Summary" dashboard (gridster-item > s247-widget-compiler >
  // .dashboard-widget-box). Real structure:
  //   <gridster-item>
  //     <div id="widgets-custom-{ID}">
  //       <s247-widget-compiler>
  //         <div class="dashboard-widget-box">
  //           <div class="dashboard-widget-header">
  //             <div class="widget-title-row"><span title="{entity}\nPeriod: ...\nData Source: ...">{entity}</span></div>
  //           </div>
  //           <div id="widgetBodyDiv-{ID}" class="widget-body-div">
  //             <s247-numerical-widget> (or other s247-*-widget tag = chart type)
  //               ... nested divs with title="{Widget Name}", title="{value}", title="{entity again}"
  //
  // If Site24x7 changes this markup later, or a different widget type
  // renders differently, check Console for [dashboard-sync][match] logs
  // to see what's actually being resolved.

  function getDashboardIdentity() {
    const titleEl = document.querySelector('.dashboard-title, .db-title, h1.title');
    const title = titleEl?.textContent.trim() || document.title.replace(' - Site24x7', '').trim() || null;
    console.log('[dashboard-sync][title]', {
      matched_element: titleEl ? { tag: titleEl.tagName, class: titleEl.className, text: titleEl.textContent.trim() } : null,
      fallback_document_title: document.title,
      resolved_title: title,
    });
    return { url: location.href, title };
  }

  function getGridWidgets() {
    const items = document.querySelectorAll('gridster-item');
    const widgets = [];
    const seenKeys = new Set(); // safety net against any remaining dupes

    items.forEach((item) => {
      // Widget ID lives on a nested element's id, e.g. id="widgets-custom-574361000000436003"
      const idHost = item.querySelector('[id^="widgets-custom-"]');
      const widgetId = idHost ? idHost.id.replace('widgets-custom-', '') : null;

      // The header span shows the entity/data-source name, with a tooltip
      // (title attribute) containing "Period:", "Unit of Time:", and
      // "Data Source:" lines on separate lines -- parse those out.
      const headerSpan = item.querySelector('.widget-title-row .text-overflow-ellipsis, .widget-title-row span[title]');
      const headerTooltip = headerSpan?.getAttribute('title') || '';
      const entityName = headerTooltip.split('\n')[0]?.trim() || headerSpan?.textContent.trim() || null;
      const periodMatch = headerTooltip.match(/Period:\s*(.+)/);
      const dataSourceMatch = headerTooltip.match(/Data Source:\s*(.+)/);
      const periodLabel = item.querySelector('.widget-period-label')?.getAttribute('title') || null;

      // The widget's real name/type label (e.g. "Overall Disk Usage") was
      // assumed to live in the widget body, NOT the header span -- but
      // real captured screenshots show the header span (.widget-title-row)
      // IS the actual visible widget title (e.g. "Throughput of analytics"),
      // while the body-label lookup below often finds nothing and returns
      // null, silently falling back to the raw numeric widget_id as the
      // display name. Header span now wins; body label is kept only as a
      // fallback for whatever widget types don't populate a header span.
      const bodyLabels = item.querySelectorAll('[id^="widgetBodyDiv-"] [title]');
      const bodyLabelName = bodyLabels[0]?.getAttribute('title') || null;
      const name = entityName || bodyLabelName || null;

      // Chart/widget-type hint from the inner Angular component's tag name,
      // e.g. <s247-numerical-widget> -> "numerical".
      const bodyHost = item.querySelector('[id^="widgetBodyDiv-"]');
      const innerComponent = bodyHost
        ? Array.from(bodyHost.children).find((el) => el.tagName.toLowerCase().startsWith('s247-'))
        : null;
      const type = innerComponent
        ? innerComponent.tagName.toLowerCase().replace(/^s247-/, '').replace(/-widget$/, '')
        : null;

      // Skip anything we couldn't identify at all -- better to under-report
      // than to send junk placeholder widgets into the app.
      if (!name && !widgetId) return;

      // Safety net: if two matched elements still resolve to the same
      // identity (same widget_id, or same name when no id is present),
      // only keep the first.
      const dedupeKey = widgetId || `name:${name}`;
      if (seenKeys.has(dedupeKey)) return;
      seenKeys.add(dedupeKey);

      widgets.push({
        widget_id: widgetId || undefined,
        name,
        type,
        meta: {
          'Data Source': dataSourceMatch?.[1]?.trim() || entityName || null,
          Period: periodMatch?.[1]?.trim() || periodLabel || null,
        },
      });
      console.log('[dashboard-sync][match]', { tag: item.tagName, widgetId, name, type, entityName, bodyLabelName });
    });

    console.log(`[dashboard-sync] found ${items.length} gridster-item(s), resolved ${widgets.length} widget(s)`);
    return widgets;
  }

  let lastSentKey = null;

  function maybeSendDashboardSnapshot() {
    const widgets = getGridWidgets();
    if (widgets.length === 0) {
      console.log('[dashboard-sync] no widgets found on this page -- selectors in getGridWidgets() likely need adjusting for the real markup.');
      return;
    }

    const { url, title } = getDashboardIdentity();
    const key = JSON.stringify({ url, count: widgets.length, names: widgets.map((w) => w.name) });
    if (key === lastSentKey) return; // no change since last send
    lastSentKey = key;

    const payload = {
      widgets,
      dashboard_url: url,
      dashboard_title: title,
      captured_at: new Date().toISOString(),
    };

    fetch('http://localhost:8000/api/widgets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => console.log('[dashboard-sync] sent', widgets.length, 'widget(s) —', data))
      .catch((err) => console.log('[dashboard-sync] could not reach http://localhost:8000 — is your app running? ', err));
  }

  // Debounce-with-max-wait: Site24x7's gridster grid continuously
  // regenerates internal layout helper elements (gridster-column,
  // gridster-row) on every reflow, which counts as DOM mutations. A plain
  // debounce that resets on every mutation can starve forever if those
  // helper mutations fire more often than the debounce window -- meaning
  // maybeSendDashboardSnapshot() would only ever run once, too early,
  // before real widgets exist. The maxWaitTimer guarantees a check happens
  // at least every MAX_WAIT_MS regardless of continued mutation noise.
  const DEBOUNCE_MS = 800;
  const MAX_WAIT_MS = 3000;
  let debounceTimer = null;
  let maxWaitTimer = null;

  function scheduleSnapshotCheck() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runSnapshotCheck, DEBOUNCE_MS);
    if (!maxWaitTimer) {
      maxWaitTimer = setTimeout(runSnapshotCheck, MAX_WAIT_MS);
    }
  }

  function runSnapshotCheck() {
    clearTimeout(debounceTimer);
    clearTimeout(maxWaitTimer);
    maxWaitTimer = null;
    maybeSendDashboardSnapshot();
  }

  scheduleSnapshotCheck();
  const gridObserver = new MutationObserver(scheduleSnapshotCheck);
  gridObserver.observe(document.body, { childList: true, subtree: true });

  })();
}