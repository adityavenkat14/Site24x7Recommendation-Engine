Configure Environment (.env)
Open the extension on chrome developer mode, reload it 
Run app.py and open index.html

# How the Recommendation Engine Works

This document explains the two separate recommendation systems in the app:
**(1) which widgets to suggest**, and **(2) what settings to pre-fill for a
widget once it's added**.

---

## 1. Widget Suggestions — "What should I add next?"

This is a **3-tier hybrid**, not a single algorithm. Each candidate widget
type gets scored, and the highest-scoring tier that has real data wins.

### Tier 1 — Co-occurrence (primary signal)
Treats each dashboard as a "basket" and its widgets as "items" — the classic
market-basket / association-rule approach.

- **Data source:** `widget_configs` (`template_id`, `widget_id`, `chart_type`,
  `category`) — chosen over `dashboard_defaults` because it has `chart_type`
  directly, with no extra join needed.
- **Build:** widgets are bucketed into generic **type** labels (not raw
  `widget_id`, since that's tied to one specific monitor and won't repeat
  across dashboards). Every pair of types that appears together on the same
  dashboard increments a `type_A × type_B` co-occurrence count.
- **Score:** for a dashboard, and for each candidate type not yet on it, we
  look up its co-occurrence with types *already* on the dashboard and
  compute `P(B | A) = count(A, B) / count(A)` — the standard "confidence"
  metric from association-rule mining.
- **Catch:** this needs volume. With very few dashboards, most pair counts
  are 0 or 1 and the signal is close to meaningless — that's what Tier 2 is
  for.

### Tier 2 — Popularity (fallback when co-occurrence is thin)
- **Data source:** same `widget_configs` table, but counts how often each
  widget type has been used on *any* dashboard, without requiring it to have
  paired with anything specific.
- **Why it exists:** unlike co-occurrence, this has signal even from a
  single dashboard, so it stays useful in the early/low-volume stage the
  account is currently in.
- **Score:** scored lower than a direct co-occurrence hit, and jittered
  (`random.uniform(-3, 3)`) so ties don't always render in the same order.

### Tier 3 — Random (cold start only)
- Only kicks in when a widget type has **zero** usage data anywhere on the
  account — no co-occurrence, no popularity.
- Instead of falling back to the catalog's alphabetical SQL order (which
  made results feel "fixed"), it assigns a small randomized score per
  request.
- Still only shuffles among the **real, extension-captured catalog
  entries** — it never invents a widget that doesn't exist on the account.

### What this replaced
The original version was a **category + config-agreement** recommender:
it grouped the real widget catalog by category, filtered out anything
already on the dashboard, and ranked candidates by how *consistently* that
widget type's settings had been configured historically (see confidence
scoring below) — not by pairing frequency. That config-agreement signal
still powers the settings pre-fill (Section 2); it's no longer what ranks
*which widgets* get suggested.

### Approaches considered but not implemented
- **Content-based** (recommend by shared category/attributes) — partially
  covered already via the category grouping.
- **Collaborative filtering** — would need usage patterns across multiple
  users/accounts; not applicable to a single-account tool.

---

## 2. Settings Suggestion — "What config should this widget use?"

Once a widget type is chosen, `_find_real_config_for_type_label()` looks at
every real observation of that chart type across the account
(`widget_config_observations`, captured passively by the browser extension)
and checks whether those observations *agree* on the same Resource Type /
Show option / Time Period.

**Confidence score:**
```
confidence = (% agreement across observations) × (sample-size dampening)
```
This answers *"how consistently has this widget type been configured the
same way"* — it is unrelated to how often the widget type appears alongside
others (that's the co-occurrence logic above). If there's no observation
data yet for a chart type, `sample_size` comes back as `0` and the UI shows
"No usage data yet" instead of a fabricated suggestion.

---

## Key design principle across both systems

Everything is grounded in **real, extension-captured data** — the actual
widget catalog and actual observed configs/pairings from the account. When
data is too thin for a given tier, the system degrades gracefully to a
lower tier rather than inventing plausible-looking but fake recommendations.