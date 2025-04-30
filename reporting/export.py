"""
HTML and CSV report export.
"""

from __future__ import annotations

import csv as csv_mod
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Template

from config import REPORT_OUTPUT_DIR, CURRENCY_SYMBOL
from db.models import Alert, Session
from reporting.summary import generate_summary
from utils import fmt_currency

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML template (embedded so the project has zero external template deps)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Subscription Leak Report</title>
<style>
  :root { --bg: #f7f8fa; --card: #fff; --accent: #4f46e5; --danger: #dc2626; --warn: #f59e0b; --ok: #16a34a; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: var(--bg); color: #1e293b; line-height: 1.6; padding: 2rem; }
  h1 { color: var(--accent); margin-bottom: .5rem; }
  .meta { color: #64748b; margin-bottom: 2rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .card { background: var(--card); border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .card .label { font-size: .85rem; color: #64748b; }
  .card .value { font-size: 1.5rem; font-weight: 700; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 2rem; background: var(--card);
          border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  th, td { padding: .75rem 1rem; text-align: left; border-bottom: 1px solid #e2e8f0; }
  th { background: var(--accent); color: #fff; font-weight: 600; }
  tr:last-child td { border-bottom: none; }
  .sev-high { color: var(--danger); font-weight: 700; }
  .sev-medium { color: var(--warn); font-weight: 600; }
  .sev-low { color: var(--ok); }
  .section-title { font-size: 1.25rem; font-weight: 700; margin: 1.5rem 0 .75rem; }
  pre { white-space: pre-wrap; font-size: .85rem; color: #475569; }
</style>
</head>
<body>
<h1>Subscription Leak Report</h1>
<p class="meta">Generated {{ generated_at }} | {{ summary.total_transactions }} transactions analysed
   ({{ summary.date_range.first }} to {{ summary.date_range.last }})</p>

<div class="cards">
  <div class="card">
    <div class="label">Active Subscriptions</div>
    <div class="value">{{ summary.subscription_count }}</div>
  </div>
  <div class="card">
    <div class="label">Est. Annual Cost</div>
    <div class="value">{{ annual_cost }}</div>
  </div>
  <div class="card">
    <div class="label">High-Severity Alerts</div>
    <div class="value sev-high">{{ summary.alerts_by_severity.high }}</div>
  </div>
  <div class="card">
    <div class="label">Total Alerts</div>
    <div class="value">{{ total_alerts }}</div>
  </div>
</div>

<div class="section-title">Detected Subscriptions</div>
<table>
<tr><th>Merchant</th><th>Frequency</th><th>Amount</th><th>Annual Cost</th><th>Regularity</th><th>Last Seen</th></tr>
{% for s in summary.active_subscriptions %}
<tr>
  <td>{{ s.merchant }}</td>
  <td>{{ s.frequency }}</td>
  <td>{{ currency }}{{ "%.2f"|format(s.median_amount) }}</td>
  <td>{{ currency }}{{ "%.2f"|format(s.annual_cost) }}</td>
  <td>{{ "%.0f"|format(s.regularity * 100) }}%</td>
  <td>{{ s.last_seen }}</td>
</tr>
{% endfor %}
</table>

<div class="section-title">Alerts</div>
<table>
<tr><th>Severity</th><th>Type</th><th>Merchant</th><th>Title</th><th>Detail</th></tr>
{% for a in alerts %}
<tr>
  <td class="sev-{{ a.severity }}">{{ a.severity | upper }}</td>
  <td>{{ a.alert_type }}</td>
  <td>{{ a.merchant }}</td>
  <td>{{ a.title }}</td>
  <td><pre>{{ a.detail }}</pre></td>
</tr>
{% endfor %}
</table>

</body>
</html>
""")


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------


def export_html(output: str | Path | None = None) -> Path:
    """Generate an HTML report and write it to *output*."""
    session = Session()
    try:
        summary = generate_summary(session)
        alerts_raw = (
            session.query(Alert)
            .order_by(Alert.severity, Alert.alert_type)
            .all()
        )
        alerts = [
            {
                "severity": a.severity,
                "alert_type": a.alert_type,
                "merchant": a.merchant,
                "title": a.title,
                "detail": a.detail or "",
            }
            for a in alerts_raw
        ]
    finally:
        session.close()

    total_alerts = sum(summary["alerts_by_severity"].values())

    html = _HTML_TEMPLATE.render(
        summary=summary,
        alerts=alerts,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        annual_cost=fmt_currency(summary["estimated_annual_cost"]),
        total_alerts=total_alerts,
        currency=CURRENCY_SYMBOL,
    )

    if output is None:
        REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = REPORT_OUTPUT_DIR / f"report_{datetime.now():%Y%m%d_%H%M%S}.html"
    else:
        output = Path(output)

    output.write_text(html, encoding="utf-8")
    logger.info("HTML report written to %s", output)
    return output


def export_csv(output: str | Path | None = None) -> Path:
    """Export alerts as a CSV file."""
    session = Session()
    try:
        alerts = (
            session.query(Alert)
            .order_by(Alert.severity, Alert.alert_type)
            .all()
        )
    finally:
        session.close()

    if output is None:
        REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = REPORT_OUTPUT_DIR / f"alerts_{datetime.now():%Y%m%d_%H%M%S}.csv"
    else:
        output = Path(output)

    with open(output, "w", newline="", encoding="utf-8") as fh:
        writer = csv_mod.writer(fh)
        writer.writerow(
            ["severity", "type", "merchant", "title", "detail", "est_annual_cost"]
        )
        for a in alerts:
            writer.writerow(
                [a.severity, a.alert_type, a.merchant, a.title, a.detail, a.estimated_annual_cost]
            )

    logger.info("CSV report written to %s", output)
    return output
