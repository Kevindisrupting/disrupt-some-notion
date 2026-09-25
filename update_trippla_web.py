"""Besøk på trippla.no (Google Analytics 4) -> Notion «Trippel A – månedsmålinger».

Kjøres ukentlig fra GitHub Actions. Innlogging mot Google skjer via
Workload Identity Federation (ingen nøkkel lagret). Skriver inneværende
og forrige måned. Rader med Datastatus «Kontrollert» røres ikke.
Måneder før GA_START_MONTH hoppes over (der ligger Squarespace-tall).
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import requests
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest

GA_PROPERTY = os.environ.get("GA_PROPERTY", "555996378")
NOTION_DB = "e860eacb9eae475baee4fda72966c99b"  # Trippel A – månedsmålinger
NOTION_API = "https://api.notion.com/v1"
TZ = ZoneInfo("Europe/Oslo")
MONTHS = ["Januar", "Februar", "Mars", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Desember"]


def gh_warn(msg):
    print(f"::warning::{msg}")


def month_start(d):
    return d.replace(day=1)


def prev_month(d):
    return month_start(month_start(d) - dt.timedelta(days=1))


def month_end(d):
    nxt = (month_start(d) + dt.timedelta(days=32)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def ga_sessions(client, start, end):
    req = RunReportRequest(
        property=f"properties/{GA_PROPERTY}",
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        metrics=[Metric(name="sessions")],
    )
    resp = client.run_report(req)
    if not resp.rows:
        return 0
    return int(resp.rows[0].metric_values[0].value)


def notion_headers():
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def find_row(title):
    r = requests.post(f"{NOTION_API}/databases/{NOTION_DB}/query", headers=notion_headers(),
                      json={"filter": {"property": "Måned", "title": {"equals": title}}}, timeout=30)
    r.raise_for_status()
    res = r.json()["results"]
    return res[0] if res else None


def write_row(month, visits, today):
    title = f"{MONTHS[month.month - 1]} {month.year}"
    props = {
        "Besøk på hjemmesiden": {"number": visits},
        "Datastatus": {"select": {"name": "Foreløpig"}},
        "Oppdatert": {"date": {"start": today.isoformat()}},
        "Kildenotat": {"rich_text": [{"text": {"content":
            f"Google Analytics 4 (økter), hentet automatisk {today.strftime('%d.%m.%Y')}."}}]},
    }
    row = find_row(title)
    if row:
        status = (row["properties"].get("Datastatus", {}).get("select") or {}).get("name")
        if status == "Kontrollert":
            print(f"{title}: Kontrollert – ikke endret")
            return
        r = requests.patch(f"{NOTION_API}/pages/{row['id']}", headers=notion_headers(),
                           json={"properties": props}, timeout=30)
    else:
        props["Måned"] = {"title": [{"text": {"content": title}}]}
        props["Periode"] = {"date": {"start": month.isoformat()}}
        r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(),
                          json={"parent": {"database_id": NOTION_DB}, "properties": props}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:300]}")
    print(f"{title}: {visits} besøk skrevet")


def main():
    today = dt.datetime.now(TZ).date()
    ga_start = dt.date.fromisoformat(os.environ.get("GA_START_MONTH", "2026-10") + "-01")
    dry = os.environ.get("DRY_RUN", "").lower() == "true"
    client = BetaAnalyticsDataClient()

    for m in (prev_month(today), month_start(today)):
        if m < ga_start:
            print(f"{m:%Y-%m}: før GA_START_MONTH – hopper over (Squarespace-tall beholdes)")
            continue
        end = min(month_end(m), today)
        visits = ga_sessions(client, m, end)
        print(f"{m:%Y-%m}: {visits} økter ({m} – {end})")
        if not dry:
            write_row(m, visits, today)

    if dry:
        # Testkall: siste 7 dager, bare for å bekrefte at tilgangen virker
        print("Siste 7 dager:", ga_sessions(client, today - dt.timedelta(days=7), today), "økter")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"::error::{e}")
        sys.exit(1)
