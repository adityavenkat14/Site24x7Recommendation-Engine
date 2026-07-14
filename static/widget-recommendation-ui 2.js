// Renders the real widget catalog (loaded by WidgetRecommendationEngine)
// inside the Add Widget modal, then a config step (Chart Type / Resource
// Type / Show / Time Period + a real monitor/metric link) pre-filled with
// the most commonly used combo for that chart type, before saving.
class WidgetRecommendationUI {
  constructor(engine, containerId, opts = {}) {
    this.engine = engine;
    this.container = document.getElementById(containerId);
    this.currentType = null;
    this.templateId = opts.templateId || null;
    this.username = opts.username || "admin";

    this.CHART_TYPES = [
      { id: "TimeChart", label: "Line Chart" },
      { id: "AreaChart", label: "Area Chart" },
      { id: "PieChart", label: "Pie Chart" },
      { id: "HorizontalBar", label: "Horizontal Bar" },
      { id: "VerticalBar", label: "Vertical Bar" }
    ];

    this.pendingWidget = null;   // {widget, type, category}
    this.pendingConfig = null;   // {chartType, resourceType, showOption, timePeriod}
    this.suggestion = null;      // last response from getConfigSuggestion
    this.monitors = [];          // cached live monitor list
    this.metricsByMonitor = {};  // monitorId -> {group, metrics}
    this.selectedMonitorId = null;
    this.selectedMetric = null;  // {id, name}
  }

  async init() {
    this.container.innerHTML = `<p>Loading real widget catalog from Site24x7...</p>`;
    await this.engine.load();
    await this.engine.loadStaticOptions();
    if (this.engine.getResourceTypes().length === 0) {
      this.container.innerHTML = `<p>No widget catalog captured yet. Open Site24x7's Add Widget panel in Chrome (with the sync extension running), then reopen this.</p>`;
      return;
    }
    this.renderResourceTypeSelector();
  }

  renderResourceTypeSelector() {
    const types = this.engine.getResourceTypes();
    this.container.innerHTML = `
      <div class="widget-recommendation-selector">
        <div class="recommendation-header">
          <h3>📌 Select What to Monitor</h3>
          <p>Real categories from your Site24x7 account</p>
        </div>
        <div class="resource-type-tabs">
          ${types.map((t) => `
            <button class="resource-tab" data-type="${t}" onclick="window.widgetUI.selectResourceType('${t}')">
              ${this.engine.getRecommendations(t).category}
            </button>`).join("")}
        </div>
        <div id="recommendations-container" style="display:none;"></div>
      </div>`;
  }

  selectResourceType(type) {
    this.currentType = type;
    document.querySelectorAll(".resource-tab").forEach((b) => b.classList.remove("active"));
    document.querySelector(`[data-type="${type}"]`).classList.add("active");
    this.renderRecommendations(type);
  }

  async renderRecommendations(type) {
    const cat = this.engine.getRecommendations(type);
    if (!cat) return;

    const c = document.getElementById("recommendations-container");
    c.style.display = "block";
    c.innerHTML = `
      <div class="recommendations-panel">
        <div class="recommendations-header"><h4>${cat.category}</h4><p>${cat.description || ""}</p></div>
        <div id="category-hint"></div>
        <div class="search-box"><input type="text" placeholder="Search widgets..." onkeyup="window.widgetUI.filterWidgets(this.value)"></div>
        <div class="widgets-grid">
          ${cat.widgets.map((w) => `
            <div class="widget-card" data-widget-id="${w.widget_item_id}">
              <div class="widget-card-header"><h5>${w.type_label}</h5></div>
              ${w.is_live ? '<div class="widget-meta"><span class="badge badge-type">Live</span></div>' : ""}
              <button class="add-widget-btn" onclick="window.widgetUI.selectWidget('${w.widget_item_id}','${type}')">+ Add Widget</button>
            </div>`).join("")}
        </div>
      </div>`;

    // Quick, non-blocking hint: what's typically picked for widgets in this
    // category, based on the default (most common) chart type. Uses one
    // shared fetch rather than one per card.
    try {
      const data = await this.engine.getConfigSuggestion(this.CHART_TYPES[0].id);
      const hintEl = document.getElementById("category-hint");
      if (!hintEl) return; // user navigated away before this resolved
      if (data.sample_size > 0 && data.suggestion) {
        const s = data.suggestion;
        const parts = [];
        if (s.resource_type.value) parts.push(`${s.resource_type.value} scope`);
        if (s.time_period.value) parts.push(s.time_period.value);
        hintEl.innerHTML = `<p style="font-size:12px; color:#7f8c8d; margin:-8px 0 12px;">💡 Widgets like these are commonly set up with ${parts.join(", ")} (based on ${data.sample_size} real observation${data.sample_size === 1 ? "" : "s"}) — you'll be able to fine-tune this per widget.</p>`;
      }
    } catch (e) { /* non-critical, ignore */ }
  }

  filterWidgets(term) {
    const cat = this.engine.getRecommendations(this.currentType);
    const t = term.toLowerCase();
    document.querySelectorAll(".widget-card").forEach((card) => {
      const id = card.getAttribute("data-widget-id");
      const w = cat.widgets.find((w) => w.widget_item_id === id);
      card.style.display = w && (w.type_label || "").toLowerCase().includes(t) ? "block" : "none";
    });
  }

  // ---- Step 2: config step ----

  async selectWidget(id, type) {
    const cat = this.engine.getRecommendations(type);
    const widget = cat.widgets.find((w) => w.widget_item_id === id);
    if (!widget) return;
    this.pendingWidget = { widget, type, category: cat.category };
    this.selectedMonitorId = null;
    this.selectedMetric = null;

    const c = document.getElementById("recommendations-container");
    c.innerHTML = `<p>Finding the best settings for this widget...</p>`;

    // Config suggestion + live monitor list can load in parallel.
    const [_, monitors] = await Promise.all([
      this.loadSuggestion(this.CHART_TYPES[0].id),
      this.engine.loadLiveMonitors()
    ]);
    this.monitors = monitors;

    // Auto-pick the first live monitor as a sensible default so the
    // "⚡ Add with Suggested Settings" button works with zero clicks.
    if (this.monitors.length > 0) {
      await this.selectMonitor(this.monitors[0].monitor_id, /*rerender=*/false);
    }

    this.renderConfigStep();
  }

  async loadSuggestion(chartType) {
    let data = null;
    try {
      data = await this.engine.getConfigSuggestion(chartType);
    } catch (e) {
      data = { sample_size: 0, suggestion: null };
    }
    this.suggestion = data;
    const s = data.suggestion;
    this.pendingConfig = {
      chartType,
      resourceType: (s && s.resource_type.value) || this.engine.resourceTypes[0] || "All Monitors",
      showOption: (s && s.show_option.value) || this.engine.showOptions[0] || "Latest 50 Active Monitors",
      timePeriod: (s && s.time_period.value) || this.engine.timePeriods[0] || "Last Hour"
    };
  }

  async selectMonitor(monitorId, rerender = true) {
    this.selectedMonitorId = monitorId;
    if (!this.metricsByMonitor[monitorId]) {
      this.metricsByMonitor[monitorId] = await this.engine.loadMonitorMetrics(monitorId);
    }
    const metrics = this.metricsByMonitor[monitorId].metrics || [];
    this.selectedMetric = metrics.length > 0 ? metrics[0] : null;
    if (rerender) this.renderConfigStep();
  }

  onMonitorDropdownChange(monitorId) {
    this.selectMonitor(monitorId, true);
  }

  onMetricDropdownChange(metricId) {
    const metrics = (this.metricsByMonitor[this.selectedMonitorId] || {}).metrics || [];
    this.selectedMetric = metrics.find((m) => m.widget_id === metricId) || this.selectedMetric;
  }

  confidenceBadge(field) {
    const s = this.suggestion && this.suggestion.suggestion;
    if (!s || !s[field] || s[field].confidence == null) return "";
    return `<span class="badge badge-usecase" style="margin-left:8px;">${s[field].confidence}% match</span>`;
  }

  renderConfigStep() {
    const { widget, type } = this.pendingWidget;
    const cfg = this.pendingConfig;
    const sampleSize = this.suggestion ? this.suggestion.sample_size : 0;

    const optionsSelect = (id, options, current, onchange) => `
      <select id="${id}" class="cfg-select" ${onchange ? `onchange="${onchange}"` : ""}
        style="width:100%; padding:8px; border:1px solid #e0e6ed; border-radius:6px; font-size:13px;">
        ${options.map((o) => `<option value="${o}" ${o === current ? "selected" : ""}>${o}</option>`).join("")}
      </select>`;

    // Monitor-link section: only meaningful if we have an auth token / any
    // monitors at all. If not, skip it gracefully rather than blocking.
    let monitorSectionHTML = "";
    if (!localStorage.getItem("zoho_access_token")) {
      monitorSectionHTML = `
        <div style="margin-bottom:16px; padding:12px; background:#fff8e1; border-radius:6px; font-size:12px; color:#7c6a1f;">
          Not connected to your Site24x7 account — this widget will be added as a placeholder without live data.
          <button class="resource-tab" style="margin-top:8px;" onclick="executeSessionAuthentication()">Connect Account</button>
        </div>`;
    } else if (this.monitors.length === 0) {
      monitorSectionHTML = `
        <div style="margin-bottom:16px; padding:12px; background:#fff8e1; border-radius:6px; font-size:12px; color:#7c6a1f;">
          No monitors found on your account — this widget will be added as a placeholder without live data.
        </div>`;
    } else {
      const metricsInfo = this.metricsByMonitor[this.selectedMonitorId] || { metrics: [] };
      const metricOptions = metricsInfo.metrics.length > 0
        ? metricsInfo.metrics.map((m) => `<option value="${m.widget_id}" ${this.selectedMetric && this.selectedMetric.widget_id === m.widget_id ? "selected" : ""}>${m.name}</option>`).join("")
        : `<option value="">No metrics available for this monitor</option>`;

      monitorSectionHTML = `
        <div style="margin-bottom:20px;">
          <label style="font-size:13px; font-weight:600; color:#2c3e50; display:block; margin-bottom:8px;">Link to a Real Monitor</label>
          <div style="display:grid; gap:10px;">
            <select id="cfg-monitor" onchange="window.widgetUI.onMonitorDropdownChange(this.value)"
              style="width:100%; padding:8px; border:1px solid #e0e6ed; border-radius:6px; font-size:13px;">
              ${this.monitors.map((m) => `<option value="${m.monitor_id}" ${m.monitor_id === this.selectedMonitorId ? "selected" : ""}>${m.display_name} (${m.monitor_type})</option>`).join("")}
            </select>
            <select id="cfg-metric" onchange="window.widgetUI.onMetricDropdownChange(this.value)"
              style="width:100%; padding:8px; border:1px solid #e0e6ed; border-radius:6px; font-size:13px;">
              ${metricOptions}
            </select>
          </div>
        </div>`;
    }

    const html = `
      <div class="recommendations-panel">
        <div class="recommendations-header">
          <h4>Configure: ${widget.type_label}</h4>
          <p>${sampleSize > 0
            ? `Pre-filled from ${sampleSize} real config${sampleSize === 1 ? "" : "s"} captured for this chart type.`
            : `No usage data captured yet for this chart type — using defaults.`}</p>
        </div>

        <div style="margin-bottom:16px;">
          <label style="font-size:13px; font-weight:600; color:#2c3e50; display:block; margin-bottom:8px;">Chart Type</label>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            ${this.CHART_TYPES.map((ct) => `
              <button type="button" class="resource-tab ${ct.id === cfg.chartType ? "active" : ""}"
                onclick="window.widgetUI.onChartTypeChange('${ct.id}')">${ct.label}</button>`).join("")}
          </div>
        </div>

        <div style="display:grid; grid-template-columns:1fr; gap:14px; margin-bottom:20px;">
          <div>
            <label style="font-size:13px; font-weight:600; color:#2c3e50;">Resource Type${this.confidenceBadge("resource_type")}</label>
            <div style="margin-top:6px;">${optionsSelect("cfg-resource-type", this.engine.resourceTypes, cfg.resourceType)}</div>
          </div>
          <div>
            <label style="font-size:13px; font-weight:600; color:#2c3e50;">Show${this.confidenceBadge("show_option")}</label>
            <div style="margin-top:6px;">${optionsSelect("cfg-show-option", this.engine.showOptions, cfg.showOption)}</div>
          </div>
          <div>
            <label style="font-size:13px; font-weight:600; color:#2c3e50;">Time Period${this.confidenceBadge("time_period")}</label>
            <div style="margin-top:6px;">${optionsSelect("cfg-time-period", this.engine.timePeriods, cfg.timePeriod)}</div>
          </div>
        </div>

        ${monitorSectionHTML}

        <div style="display:flex; flex-direction:column; gap:10px;">
          <button class="apply-widgets-btn" style="background:#27ae60;" onclick="window.widgetUI.saveWidget(true)">⚡ Add with Suggested Settings</button>
          <button class="apply-widgets-btn" onclick="window.widgetUI.saveWidget(false)">Add Widget</button>
          <button class="resource-tab" onclick="window.widgetUI.renderRecommendations('${type}')">← Back</button>
        </div>
      </div>`;

    const c = document.getElementById("recommendations-container");
    c.innerHTML = html;
    c.style.display = "block";
  }

  async onChartTypeChange(chartType) {
    // A new chart type means new suggestions are more useful than stale
    // manual picks, so we refetch and re-prefill on chart type change.
    // Monitor/metric selection is left untouched — that's independent of
    // chart type.
    await this.loadSuggestion(chartType);
    this.renderConfigStep();
  }

  async saveWidget(useSuggested) {
    if (!this.templateId) {
      alert("No dashboard selected — name your dashboard first.");
      return;
    }
    const { widget, category } = this.pendingWidget;

    const resourceType = useSuggested
      ? this.pendingConfig.resourceType
      : document.getElementById("cfg-resource-type").value;
    const showOption = useSuggested
      ? this.pendingConfig.showOption
      : document.getElementById("cfg-show-option").value;
    const timePeriod = useSuggested
      ? this.pendingConfig.timePeriod
      : document.getElementById("cfg-time-period").value;
    const chartType = this.pendingConfig.chartType;

    const monitor = this.monitors.find((m) => m.monitor_id === this.selectedMonitorId);
    const metricIds = (this.selectedMonitorId && this.selectedMetric)
      ? [{ id: this.selectedMetric.widget_id, name: this.selectedMetric.name }]
      : [{ id: widget.widget_item_id, name: widget.type_label }]; // fallback: placeholder, no live link

    const payload = {
      category: category,
      chart_type: chartType,
      resource_type: resourceType,
      monitor_ids: this.selectedMonitorId ? [this.selectedMonitorId] : [],
      monitor_type: monitor ? monitor.monitor_type : "Monitor",
      metric_ids: metricIds,
      show_option: showOption,
      time_period: timePeriod,
      display_name: widget.type_label,
      username: this.username
    };

    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/dashboards/${encodeURIComponent(this.templateId)}/widgets/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status !== "success") {
        alert(data.message || "Could not add widget.");
        return;
      }
      if (typeof window.onWidgetAdded === "function") {
        window.onWidgetAdded(data.widget_id, widget.type_label, {
          chartType, resourceType, showOption, timePeriod,
          linkedMonitor: monitor ? monitor.display_name : null
        });
      }
      this.pendingWidget = null;
      this.pendingConfig = null;
    } catch (err) {
      alert("Could not add widget: " + err);
    }
  }
}

if (typeof window !== "undefined") window.WidgetRecommendationUI = WidgetRecommendationUI;
if (typeof module !== "undefined" && module.exports) module.exports = WidgetRecommendationUI;