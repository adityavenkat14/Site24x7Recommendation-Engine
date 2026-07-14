// Loads the real widget category/type catalog captured from Site24x7
// by the browser extension, instead of a hardcoded list.
class WidgetRecommendationEngine {
  constructor() {
    this.categories = {}; // slug -> {category, description, widgets:[{widget_item_id,type_label,is_live}]}
  }

  async load() {
    const res = await fetch('http://127.0.0.1:8000/api/widget-catalog');
    const data = await res.json();
    this.categories = {};
    data.forEach((cat) => {
      const slug = cat.category.toLowerCase().replace(/[^a-z0-9]+/g, '_');
      this.categories[slug] = cat;
    });
    return this.categories;
  }

  getRecommendations(slug) {
    return this.categories[slug] || null;
  }

  getResourceTypes() {
    return Object.keys(this.categories);
  }

  searchWidgets(slug, term) {
    const cat = this.getRecommendations(slug);
    if (!cat) return [];
    const t = term.toLowerCase();
    return cat.widgets.filter((w) => (w.type_label || '').toLowerCase().includes(t));
  }

  // Static Resource Type / Show / Time Period option lists (from WIDGET_CATALOG
  // config, not the live-captured catalog above) — used to populate the
  // config-step dropdowns in the Add Widget flow.
  async loadStaticOptions() {
    const res = await fetch('http://127.0.0.1:8000/api/v1/widget-catalog');
    const data = await res.json();
    this.resourceTypes = data.resource_types || [];
    this.showOptions = data.show_options || [];
    this.timePeriods = data.time_periods || [];
    return { resourceTypes: this.resourceTypes, showOptions: this.showOptions, timePeriods: this.timePeriods };
  }

  // Most commonly used Resource Type / Show / Time Period combo for a given
  // chart type, based on real observations passively captured from the
  // Site24x7 site by the browser extension. Returns null suggestion fields
  // (with sample_size 0) if nothing's been observed yet for that chart type.
  async getConfigSuggestion(chartType) {
    const res = await fetch(`http://127.0.0.1:8000/api/v1/recommendations/widget-config?chart_type=${encodeURIComponent(chartType)}`);
    return res.json();
  }

  // Real monitors from the connected Site24x7 account, used to link a
  // catalog widget to an actual live data source (not just a label).
  async loadLiveMonitors() {
    const token = localStorage.getItem('zoho_access_token');
    if (!token) { this.liveMonitors = []; return this.liveMonitors; }
    try {
      const res = await fetch('http://127.0.0.1:8000/api/v1/monitors/live', {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) { this.liveMonitors = []; return this.liveMonitors; }
      const data = await res.json();
      this.liveMonitors = data.monitors || [];
    } catch (e) {
      this.liveMonitors = [];
    }
    return this.liveMonitors;
  }

  // Real metric list for one monitor (used to fill the second dropdown
  // once a monitor is picked).
  async loadMonitorMetrics(monitorId) {
    const token = localStorage.getItem('zoho_access_token');
    if (!token) return { group: null, metrics: [] };
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/monitors/${encodeURIComponent(monitorId)}/metrics`, {
        headers: { Authorization: 'Bearer ' + token }
      });
      if (!res.ok) return { group: null, metrics: [] };
      return res.json();
    } catch (e) {
      return { group: null, metrics: [] };
    }
  }
}

if (typeof window !== "undefined") window.WidgetRecommendationEngine = WidgetRecommendationEngine;
if (typeof module !== "undefined" && module.exports) module.exports = WidgetRecommendationEngine;