// Guard against duplicate injection: if the extension gets reloaded
// while this tab is already open, Chrome can re-run this content
// script into the SAME page context that still has the previous
// run's top-level variables alive, causing a
// "Identifier ... has already been declared" crash. Wrapping
// everything in this guard + IIFE means a second injection is a
// harmless no-op instead of a syntax error.
if (!window.__s247DeleteSyncLoaded) {
  window.__s247DeleteSyncLoaded = true;
  (function () {

  // Watches the Site24x7 DASHBOARD LISTING page (the table showing all
  // dashboards, e.g. "App trial", "Website Summary") and tells the local
  // app which dashboard names currently exist on the live site. The
  // backend then deletes any "Live Capture" dashboard whose name is no
  // longer present.
  //
  // IMPORTANT structural notes learned from real markup on this page:
  //   - Each row's <a> link has href="#/undefined" -- there is NO usable
  //     dashboard ID here, only the visible name text. Matching is done
  //     by name (dashboard_templates.template_name on the backend), not ID.
  //   - The list is <tbody infinitescroll> -- rows lazy-load as you
  //     scroll. A snapshot taken without scrolling will look "complete"
  //     even when most dashboards haven't rendered yet. loadAllRows()
  //     below force-scrolls until the row count stops growing before
  //     trusting any snapshot.
  //
  // If Site24x7's markup changes, check console logs here for what's
  // actually being matched.

  function isOnDashboardListingPage() {
    const hash = location.hash || '';
    return /^#\/home\/dashboards\/?(\?.*)?$/.test(hash);
  }

  function getVisibleDashboardNames() {
    const links = document.querySelectorAll(
      'tbody[infinitescroll] tr .sub-items-name a.ellipsis-text, tbody[infinitescroll] tr a.ellipsis-text'
    );
    return Array.from(links).map((a) => a.textContent.trim()).filter(Boolean);
  }

  function findScrollableAncestor(el) {
    let node = el;
    while (node && node !== document.body && node !== document.documentElement) {
      const style = window.getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) {
        return node;
      }
      node = node.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  }

  // Force the infinite-scroll list to fully load by repeatedly scrolling
  // to the bottom until the row count stops growing (stable for 2
  // consecutive checks), or a max attempt cap is hit as a safety valve.
  async function loadAllDashboardRows() {
    const tbody = document.querySelector('tbody[infinitescroll]');
    if (!tbody) return getVisibleDashboardNames();

    const scrollTarget = findScrollableAncestor(tbody);
    let lastCount = -1;
    let stableRounds = 0;
    const MAX_ATTEMPTS = 30;

    for (let i = 0; i < MAX_ATTEMPTS; i++) {
      const currentCount = tbody.querySelectorAll('tr').length;
      if (currentCount === lastCount) {
        stableRounds++;
        if (stableRounds >= 2) break; // same row count twice in a row -- fully loaded
      } else {
        stableRounds = 0;
      }
      lastCount = currentCount;

      scrollTarget.scrollTop = scrollTarget.scrollHeight;
      tbody.scrollTop = tbody.scrollHeight; // in case tbody itself is the scroll container
      await new Promise((resolve) => setTimeout(resolve, 400));
    }

    console.log(`[dashboard-delete-sync] finished scroll-load after row count stabilized at ${lastCount}`);
    return getVisibleDashboardNames();
  }

  let lastSentSnapshot = null;
  let isChecking = false;
  let debounceTimer = null;

  function scheduleCheck() {
    if (!isOnDashboardListingPage()) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runCheckOnce, 1200);
  }

  async function runCheckOnce() {
    if (isChecking) return; // a check is already in flight, let it finish
    isChecking = true;
    try {
      if (!isOnDashboardListingPage()) return;

      const firstRead = await loadAllDashboardRows();
      const firstKey = JSON.stringify([...firstRead].sort());

      // Confirm stability with a second read after a pause, entirely
      // within this one call -- no separate timer chain that can race
      // against this one.
      await new Promise((resolve) => setTimeout(resolve, 2000));
      if (!isOnDashboardListingPage()) return;
      const secondRead = await loadAllDashboardRows();
      const secondKey = JSON.stringify([...secondRead].sort());

      if (firstKey !== secondKey) {
        console.log('[dashboard-delete-sync] list changed between two reads -- not stable yet, will recheck on next page change', { firstRead, secondRead });
        return;
      }

      if (secondKey === lastSentSnapshot) {
        console.log(`[dashboard-delete-sync] confirmed stable at ${secondRead.length} name(s), same as already synced -- nothing to do`);
        return;
      }

      lastSentSnapshot = secondKey;
      sendSync(secondRead);
    } finally {
      isChecking = false;
    }
  }

  function sendSync(names) {
    fetch('http://localhost:8000/api/v1/dashboards/sync-live-list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dashboard_names: names }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.deleted && data.deleted.length) {
          console.log('[dashboard-delete-sync] removed', data.deleted.length, 'dashboard(s) no longer on the live site —', data.deleted);
        } else {
          console.log('[dashboard-delete-sync] synced', names.length, 'live dashboard name(s), nothing to remove');
        }
      })
      .catch((err) => console.log('[dashboard-delete-sync] could not reach http://localhost:8000 — is your app running? ', err));
  }

  setTimeout(scheduleCheck, 1500);

  window.addEventListener('hashchange', scheduleCheck);

  const listObserver = new MutationObserver(scheduleCheck);
  listObserver.observe(document.body, { childList: true, subtree: true });

  })();
}