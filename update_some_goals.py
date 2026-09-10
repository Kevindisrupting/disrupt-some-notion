import os
import sys
import requests

METRIKA_URL = "https://metrika.run/api/v1/resources/search"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

ACCOUNTS = [
    {"label":"PU Instagram","platform":"instagram","identifier":"projectundergrunn","notion_page_id":"3ba3f300-487c-80e4-a5a6-c38a7352f7a4"},
    {"label":"PU Facebook","platform":"facebook","identifier":"projectundergrunn","notion_page_id":"3ba3f300-487c-803d-970c-e6ae46df9b17"},
    {"label":"PU TikTok","platform":"tiktok","identifier":"projectundergrunn","notion_page_id":"3ba3f300-487c-803f-a8e7-ca3834da1a5b"},
    {"label":"Disrupt Instagram","platform":"instagram","identifier":"disrupt_ofc","notion_page_id":"3d63f300-487c-80e7-8ed7-fa27c12955ff"},
    {"label":"Disrupt Facebook","platform":"facebook","identifier":"disruptingAS","notion_page_id":"3d63f300-487c-80f7-b0dc-fad176d3d5cb"},
    {"label":"Disrupt TikTok","platform":"tiktok","identifier":"disrupt_ofc","notion_page_id":"3d63f300-487c-80ed-b3a4-f8bec22fae85"},
    {"label":"Valsemøllen Instagram","platform":"instagram","identifier":"valsemollenbergen","notion_page_id":"3d73f300-487c-8077-8f77-d52ea52b3280"},
    {"label":"Valsemøllen Facebook","platform":"facebook","identifier":"valsemollen","notion_page_id":"3d73f300-487c-8021-aeae-fdbe6a94de9b"},
    {"label":"HOUSEHOLD Instagram","platform":"instagram","identifier":"household_ofc","notion_page_id":"3d63f300-487c-80af-a863-d12bf186e73e"},
]

def need(name):
    v = os.getenv(name)
    if not v:
        print(f"ERROR: missing {name}")
        sys.exit(1)
    return v

def main():
    mt = need("METRIKA_TOKEN")
    nt = need("NOTION_TOKEN")

    payload = {"resources":[{"platform":a["platform"],"type":"account","identifier":a["identifier"]} for a in ACCOUNTS]}
    r = requests.post(METRIKA_URL, headers={"Authorization":f"Bearer {mt}","Content-Type":"application/json"}, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json().get("data", [])
    results = {(x.get("platform"),x.get("identifier")):x for x in data}

    updated = skipped = 0
    for a in ACCOUNTS:
        x = results.get((a["platform"],a["identifier"]))
        if not x or x.get("status") != "available":
            print(f"SKIP {a['label']}: {None if not x else x.get('status')}")
            skipped += 1
            continue

        metric = x.get("metrics",{}).get("followers",{})
        value = metric.get("value")
        if not isinstance(value,(int,float)) or value <= 0:
            print(f"SKIP {a['label']}: invalid value {value!r}")
            skipped += 1
            continue

        p = requests.patch(
            f"{NOTION_API}/pages/{a['notion_page_id']}",
            headers={"Authorization":f"Bearer {nt}","Notion-Version":NOTION_VERSION,"Content-Type":"application/json"},
            json={"properties":{"Nåverdi":{"number":int(value)}}},
            timeout=30,
        )
        p.raise_for_status()
        print(f"UPDATE {a['label']}: {int(value)} | semantic={metric.get('semantic')} | collected_at={metric.get('collected_at')}")
        updated += 1

    print(f"Done. Updated={updated}, skipped={skipped}")

if __name__ == "__main__":
    main()
