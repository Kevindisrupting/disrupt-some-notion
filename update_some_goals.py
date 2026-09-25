"""
Disrupt — SoMe → Notion

1) Ukentlig (som før): oppdaterer Nåverdi i «Mål — 2026».
2) Nytt: fyller SoMe-kolonnene i månedstabellene på «KPI – Konseptnivå»
   (Disrupt, Project Undergrunn, HOUSEHOLD – månedsmålinger).

Kjøremodus (RUN_MODE / CLOSE_MONTH):
  - auto   : den 1. i måneden (Oslo-tid) lukkes forrige måned, ellers oppdateres
             inneværende måned med løpende tall.
  - close  : lukk forrige måned (brukes av kjøringen den 1.).
  - CLOSE_MONTH=YYYY-MM : lukk en bestemt måned manuelt.

Regler:
  - Hjelpekolonner «<Plattform>-følgere ved månedsslutt» opprettes ved behov.
  - Netto nye = følgere ved månedsslutt (denne raden) − følgere ved månedsslutt
    (forrige måneds rad). Mangler forrige tall → feltet står tomt.
  - Rekkevidde fylles KUN hvis kilden gir unik rekkevidde for hele måneden.
    Metrika gir ikke dette i dag, så rekkeviddefeltene røres ikke.
    Visninger brukes aldri.
  - Datastatus → «Foreløpig». Rader med «Kontrollert» røres ikke.
  - Oppdatert → dagens dato. Kildenotat: en linje som starter med «[Auto SoMe]»
    erstattes; manuell tekst i notatet beholdes.
"""

import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

METRIKA_URL = "https://metrika.run/api/v1/resources/search"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"          # eksisterende side-oppdateringer
NOTION_VERSION_DS = "2025-09-03"       # data source-endepunkter (skjema + spørring)
OSLO = ZoneInfo("Europe/Oslo")
AUTO_PREFIX = "[Auto SoMe]"
MONTHS_NO = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
             "august", "september", "oktober", "november", "desember"]

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

# Månedstabeller (data source-ID-er fra «KPI – Konseptnivå»). Kontoene finnes
# allerede i ACCOUNTS, så dette krever ingen ekstra Metrika-kall.
MONTHLY_TABLES = [
    {"name": "Disrupt", "data_source_id": "bc48ae52-c6e0-4e9b-819d-5c5f340698ac",
     "accounts": {"Instagram": ("instagram", "disrupt_ofc"), "TikTok": ("tiktok", "disrupt_ofc")}},
    {"name": "Project Undergrunn", "data_source_id": "c34063da-2639-457b-ad7b-6b2a9755e71a",
     "accounts": {"Instagram": ("instagram", "projectundergrunn"), "TikTok": ("tiktok", "projectundergrunn")}},
    {"name": "HOUSEHOLD", "data_source_id": "c596ce67-c462-4002-a853-18cc6404d3b8",
     "accounts": {"Instagram": ("instagram", "household_ofc")}},
    {"name": "Valsemøllen", "data_source_id": "d53e68eb-5520-43c4-93c5-8359a110ae63",
     "accounts": {"Instagram": ("instagram", "valsemollenbergen")}},
]


def need(name):
    v = os.getenv(name)
    if not v:
        print(f"ERROR: missing {name}")
        sys.exit(1)
    return v


# ---------------------------------------------------------------- Metrika
def fetch_metrika(token):
    payload = {"resources": [{"platform": a["platform"], "type": "account", "identifier": a["identifier"]} for a in ACCOUNTS]}
    r = requests.post(METRIKA_URL, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=60)
    r.raise_for_status()
    return {(x.get("platform"), x.get("identifier")): x for x in r.json().get("data", [])}


def valid_followers(x):
    """Returnerer (verdi, metric) eller (None, grunn)."""
    if not x or x.get("status") != "available":
        return None, f"status={None if not x else x.get('status')}"
    metric = x.get("metrics", {}).get("followers", {})
    if metric.get("status", "available") != "available":
        return None, f"metric status={metric.get('status')}"
    value = metric.get("value")
    if not isinstance(value, (int, float)) or value <= 0:
        return None, f"invalid value {value!r}"
    return int(value), metric


# ---------------------------------------------------------------- Instagram (Meta, Instagram-innlogging)
# Ett langtids-token per konto i GitHub-secrets. Krever ingen Facebook-side.
IG_GRAPH = "https://graph.instagram.com"
IG_API = f"{IG_GRAPH}/v23.0"
IG_TOKEN_SECRETS = {
    "disrupt_ofc": "IG_TOKEN_DISRUPT",
    "projectundergrunn": "IG_TOKEN_PU",
    "household_ofc": "IG_TOKEN_HOUSEHOLD",
    "valsemollenbergen": "IG_TOKEN_VALSEMOLLEN",   # valgfri – uten token brukes Metrika
}
_ig_tokens = {}


def mask(value):
    if value and os.getenv("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}")


def gh_warn(msg):
    print(f"::warning::{msg}" if os.getenv("GITHUB_ACTIONS") else f"WARNING: {msg}")


def write_github_secret(name, value):
    """Lagrer fornyet token tilbake i repo-secret (krever GH_SECRETS_PAT med
    «Secrets: read and write» for dette repoet)."""
    pat, repo = os.getenv("GH_SECRETS_PAT"), os.getenv("GITHUB_REPOSITORY")
    if not (pat and repo):
        gh_warn(f"{name}: fornyet token ble ikke lagret (GH_SECRETS_PAT mangler) – utløper om 60 dager")
        return False
    from base64 import b64encode
    from nacl import encoding, public
    h = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}
    k = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=h, timeout=30)
    k.raise_for_status()
    box = public.SealedBox(public.PublicKey(k.json()["key"].encode(), encoding.Base64Encoder()))
    enc = b64encode(box.encrypt(value.encode())).decode()
    p = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", headers=h,
                     json={"encrypted_value": enc, "key_id": k.json()["key_id"]}, timeout=30)
    p.raise_for_status()
    return True


def ig_token(identifier):
    """Henter token og fornyer det (gyldig 60 nye dager). Fornyet token lagres i GitHub."""
    if identifier in _ig_tokens:
        return _ig_tokens[identifier]
    name = IG_TOKEN_SECRETS.get(identifier)
    tok = os.getenv(name) if name else None
    if tok:
        mask(tok)
        try:
            r = requests.get(f"{IG_GRAPH}/refresh_access_token",
                             params={"grant_type": "ig_refresh_token", "access_token": tok}, timeout=30)
            if r.ok and r.json().get("access_token"):
                new = r.json()["access_token"]
                mask(new)
                if new != tok:
                    write_github_secret(name, new)
                tok = new
            else:
                gh_warn(f"{name}: kunne ikke fornye token ({r.status_code})")
        except requests.RequestException as e:
            gh_warn(f"{name}: fornying feilet ({type(e).__name__})")
    _ig_tokens[identifier] = tok
    return tok


def ig_followers(identifier):
    """(verdi, metric-lignende dict) fra Meta, eller (None, grunn)."""
    tok = ig_token(identifier)
    if not tok:
        return None, "ingen Instagram-token"
    r = requests.get(f"{IG_API}/me", params={"fields": "username,followers_count", "access_token": tok}, timeout=30)
    if not r.ok:
        return None, f"Meta-feil {r.status_code}"
    j = r.json()
    if j.get("username", "").lower() != identifier.lower():
        return None, f"token tilhører @{j.get('username')}, ikke @{identifier}"
    v = j.get("followers_count")
    if not isinstance(v, int) or v <= 0:
        return None, f"ugyldig verdi {v!r}"
    return v, {"collected_at": datetime.now(OSLO).isoformat(timespec="seconds"), "source": "Meta Instagram API"}


def ig_net_followers(identifier, month_start):
    """Netto nye følgere i måneden (hittil) = følg − avfølg fra Meta
    (follows_and_unfollows, total_value, fordelt på follow_type). Hendelser kan
    summeres, så perioden deles i biter på maks 30 dager. Returnerer (verdi, notat)."""
    tok = ig_token(identifier)
    if not tok:
        return None, "ingen Instagram-token"
    start = datetime(month_start.year, month_start.month, 1, tzinfo=OSLO)
    end = datetime.combine(month_end(month_start) + timedelta(days=1), datetime.min.time(), tzinfo=OSLO)
    end = min(end, datetime.now(OSLO))
    follows = unfollows = 0
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=29), end)   # godt under Metas 30-dagersgrense
        r = requests.get(f"{IG_API}/me/insights", params={
            "metric": "follows_and_unfollows", "period": "day", "metric_type": "total_value",
            "breakdown": "follow_type", "since": int(cur.timestamp()), "until": int(nxt.timestamp()),
            "access_token": tok}, timeout=30)
        if not r.ok:
            return None, f"Meta ga ikke følg/avfølg ({r.status_code})"
        found = False
        for d in r.json().get("data", []):
            if d.get("name") != "follows_and_unfollows":
                continue
            for b in (d.get("total_value") or {}).get("breakdowns", []):
                for res in b.get("results", []):
                    kind = (res.get("dimension_values") or [""])[0].upper()
                    v = res.get("value") or 0
                    if kind == "FOLLOWER":
                        follows += v; found = True
                    elif kind == "NON_FOLLOWER":
                        unfollows += v; found = True
        if not found:
            return None, "Meta returnerte ingen følg/avfølg-tall"
        cur = nxt
    return follows - unfollows, f"Meta: {follows} nye følgere − {unfollows} avfølginger {start:%d.%m}–{end:%d.%m}"


def ig_month_total(identifier, month_start, metric, summable):
    """Månedstall for en Meta-metrikk (total_value). Unike metrikker (summable=False)
    hentes i ETT uttak og returnerer None hvis Meta avviser perioden. Summerbare
    metrikker hentes i biter på maks 29 dager og legges sammen."""
    tok = ig_token(identifier)
    if not tok:
        return None, "ingen Instagram-token"
    start = datetime(month_start.year, month_start.month, 1, tzinfo=OSLO)
    end = datetime.combine(month_end(month_start) + timedelta(days=1), datetime.min.time(), tzinfo=OSLO)
    end = min(end, datetime.now(OSLO))
    step = timedelta(days=29) if summable else (end - start)
    total, cur = 0, start
    while cur < end:
        nxt = min(cur + step, end)
        r = requests.get(f"{IG_API}/me/insights", params={
            "metric": metric, "period": "day", "metric_type": "total_value",
            "since": int(cur.timestamp()), "until": int(nxt.timestamp()), "access_token": tok}, timeout=30)
        if not r.ok:
            return None, f"Meta ga ikke {metric} for perioden ({r.status_code})"
        vals = [(d.get("total_value") or {}).get("value") for d in r.json().get("data", []) if d.get("name") == metric]
        if not vals or not isinstance(vals[0], int):
            return None, f"Meta returnerte ingen {metric}-verdi"
        total += vals[0]
        cur = nxt
    return total, f"Meta {metric} {start:%Y-%m-%d}–{end:%Y-%m-%d}"


# Engasjement som skrives ved månedsslutt: (Notion-kolonne, Meta-metrikk, summerbar?)
IG_ENGAGEMENT = [
    ("Instagram-engasjerte kontoer", "accounts_engaged", False),
    ("Instagram-interaksjoner", "total_interactions", True),
]


def monthly_unique_reach(platform, identifier, month_start):
    """Unik rekkevidde (unike kontoer) for HELE måneden, ett kall – aldri summert.
    Bare Instagram via Meta. Returnerer (verdi, notat). Visninger brukes aldri."""
    if platform != "instagram":
        return None, "ingen kilde for unik månedsrekkevidde"
    tok = ig_token(identifier)
    if not tok:
        return None, "ingen Instagram-token"
    start = datetime(month_start.year, month_start.month, 1, tzinfo=OSLO)
    end = datetime.combine(month_end(month_start) + timedelta(days=1), datetime.min.time(), tzinfo=OSLO)
    end = min(end, datetime.now(OSLO))
    r = requests.get(f"{IG_API}/me/insights", params={
        "metric": "reach", "period": "day", "metric_type": "total_value",
        "since": int(start.timestamp()), "until": int(end.timestamp()), "access_token": tok}, timeout=30)
    if not r.ok:
        msg = (r.json().get("error", {}) or {}).get("message", "") if r.headers.get("content-type", "").startswith("application/json") else ""
        return None, f"Meta ga ikke rekkevidde for hele perioden ({r.status_code} {msg[:80]})"
    for d in r.json().get("data", []):
        if d.get("name") == "reach":
            v = (d.get("total_value") or {}).get("value")
            if isinstance(v, int) and v >= 0:
                return v, f"Meta reach total_value {start:%Y-%m-%d}–{end:%Y-%m-%d}"
    return None, "Meta returnerte ingen reach-verdi"


# ---------------------------------------------------------------- Notion
def nh(token, version=NOTION_VERSION):
    return {"Authorization": f"Bearer {token}", "Notion-Version": version, "Content-Type": "application/json"}


def ensure_helper_columns(nt, ds_id, platforms):
    r = requests.get(f"{NOTION_API}/data_sources/{ds_id}", headers=nh(nt, NOTION_VERSION_DS), timeout=30)
    r.raise_for_status()
    existing = r.json().get("properties", {})
    missing = {f"{p}-følgere ved månedsslutt": {"number": {"format": "number_with_commas"}}
               for p in platforms if f"{p}-følgere ved månedsslutt" not in existing}
    if missing:
        p = requests.patch(f"{NOTION_API}/data_sources/{ds_id}", headers=nh(nt, NOTION_VERSION_DS), json={"properties": missing}, timeout=30)
        p.raise_for_status()
        print(f"  + la til kolonner: {', '.join(missing)}")


def find_month_row(nt, ds_id, month_start):
    body = {"filter": {"property": "Periode", "date": {"equals": month_start.isoformat()}}, "page_size": 5}
    r = requests.post(f"{NOTION_API}/data_sources/{ds_id}/query", headers=nh(nt, NOTION_VERSION_DS), json=body, timeout=30)
    r.raise_for_status()
    rows = r.json().get("results", [])
    if len(rows) > 1:
        print(f"  ! flere rader for {month_start:%Y-%m}; bruker den første")
    return rows[0] if rows else None


def num(row, prop):
    return (row or {}).get("properties", {}).get(prop, {}).get("number")


def plain_text(row, prop):
    return "".join(t.get("plain_text", "") for t in (row or {}).get("properties", {}).get(prop, {}).get("rich_text", []))


def select_name(row, prop):
    sel = (row or {}).get("properties", {}).get(prop, {}).get("select")
    return sel.get("name") if sel else None


# ---------------------------------------------------------------- måned-logikk
def month_start(d):
    return date(d.year, d.month, 1)


def prev_month(d):
    return month_start(month_start(d) - timedelta(days=1))


def month_end(ms):
    return (ms.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def month_label(ms):
    return f"{MONTHS_NO[ms.month - 1]} {ms.year}"


def resolve_target(today):
    """(målmåned, closing?) ut fra RUN_MODE / CLOSE_MONTH."""
    cm = (os.getenv("CLOSE_MONTH") or "").strip()
    if cm:
        y, m = map(int, cm.split("-"))
        return date(y, m, 1), True
    mode = (os.getenv("RUN_MODE") or "auto").strip()
    if mode == "close" or today.day == 1:
        return prev_month(today), True
    return month_start(today), False


def collected_ok_for_close(metric, target):
    """Ved lukking må tallet være hentet rundt månedsskiftet (±1 døgn)."""
    ca = metric.get("collected_at")
    if not ca:
        return False
    d = datetime.fromisoformat(ca.replace("Z", "+00:00")).astimezone(OSLO).date()
    return month_end(target) - timedelta(days=1) <= d <= month_end(target) + timedelta(days=2)


def update_monthly_tables(nt, results, today, target, closing):
    problems = 0
    prev = prev_month(target)
    for t in MONTHLY_TABLES:
        print(f"[{t['name']}] {month_label(target)} ({'sluttall' if closing else 'løpende'})")
        ensure_helper_columns(nt, t["data_source_id"], t["accounts"].keys())
        row = find_month_row(nt, t["data_source_id"], target)
        if not row:
            print(f"  ! fant ingen rad med Periode={target.isoformat()} – hopper over")
            problems += 1
            continue
        if select_name(row, "Datastatus") == "Kontrollert":
            print("  = Kontrollert – røres ikke")
            continue
        prev_row = find_month_row(nt, t["data_source_id"], prev)

        props, notes = {}, []
        for platform, key in t["accounts"].items():
            value, metric = followers(key, results)
            if value is None:
                gh_warn(f"{t['name']} {platform}: hoppet over ({metric})")
                notes.append(f"{platform}: ingen gyldig verdi ({metric})")
                problems += closing
                continue
            if closing and not collected_ok_for_close(metric, target):
                print(f"  SKIP {platform}: collected_at={metric.get('collected_at')} er ikke ved månedsslutt")
                notes.append(f"{platform}: tall ikke hentet ved månedsslutt ({metric.get('collected_at')})")
                problems += 1
                continue

            helper = f"{platform}-følgere ved månedsslutt"
            props[helper] = {"number": value}
            prev_val = num(prev_row, helper)
            net_prop = f"Netto nye {platform}-følgere"
            if isinstance(prev_val, (int, float)):
                props[net_prop] = {"number": value - int(prev_val)}
                net_txt = f"netto {value - int(prev_val):+d} mot {month_label(prev)} ({int(prev_val)})"
            else:
                # Startpunkt mangler: for Instagram regnes startpunktet ut fra Meta
                # (følgere nå − netto følg/avfølg siden månedsstart).
                net, nnote = (ig_net_followers(key[1], target) if key[0] == "instagram"
                              else (None, "ingen historikk i kilden"))
                if isinstance(net, int):
                    props[net_prop] = {"number": net}
                    net_txt = (f"netto {net:+d} ({nnote}); utledet startpunkt "
                               f"{month_label(prev)} ≈ {value - net}")
                else:
                    net_txt = f"netto ikke beregnet – mangler følgertall for {month_label(prev)} ({nnote})"
            ca = metric.get("collected_at", "?")
            src = metric.get("source", "Metrika")
            notes.append(f"{platform} {value} ({src}, hentet {ca}); {net_txt}")

            # Rekkevidde bare for hele, avsluttede måneder – aldri delmåned, aldri visninger
            if closing:
                reach, rnote = monthly_unique_reach(*key, target)
                if isinstance(reach, int):
                    props[f"{platform}-rekkevidde"] = {"number": reach}
                    notes.append(f"{platform}-rekkevidde {reach} ({rnote})")
                else:
                    notes.append(f"{platform}-rekkevidde tom: {rnote}")
                if platform == "Instagram":
                    for col, metric_name, summable in IG_ENGAGEMENT:
                        v, en = ig_month_total(key[1], target, metric_name, summable)
                        if isinstance(v, int):
                            props[col] = {"number": v}
                            notes.append(f"{col} {v} ({en})")
                        else:
                            notes.append(f"{col} tom: {en}")
            else:
                notes.append(f"{platform}-rekkevidde settes ved månedsslutt")

        if not props:
            print("  ingen tall å skrive")
            continue

        notes.append("Visninger brukes ikke som rekkevidde.")
        status_txt = "sluttall" if closing else "løpende tall, ikke endelig"
        auto_line = f"{AUTO_PREFIX} {today.isoformat()}, {status_txt}: " + " | ".join(notes)
        manual = [l for l in plain_text(row, "Kildenotat").splitlines() if not l.startswith(AUTO_PREFIX)]
        kildenotat = "\n".join(manual + [auto_line]).strip()[:2000]

        props["Datastatus"] = {"select": {"name": "Foreløpig"}}
        props["Oppdatert"] = {"date": {"start": today.isoformat()}}
        props["Kildenotat"] = {"rich_text": [{"type": "text", "text": {"content": kildenotat}}]}

        p = requests.patch(f"{NOTION_API}/pages/{row['id']}", headers=nh(nt), json={"properties": props}, timeout=30)
        p.raise_for_status()
        print(f"  UPDATE {', '.join(k for k in props if k not in ('Kildenotat',))}")
    return problems


def followers(key, results):
    """Instagram: Meta først (ferskt tall), Metrika som reserve. Andre: Metrika."""
    platform, identifier = key
    if platform == "instagram" and identifier in IG_TOKEN_SECRETS:
        v, m = ig_followers(identifier)
        if v is not None:
            return v, m
        if m != "ingen Instagram-token":
            gh_warn(f"@{identifier}: Meta feilet ({m}) – bruker Metrika")
    return valid_followers(results.get(key))


# ---------------------------------------------------------------- main
def update_goals(nt, results):
    updated = skipped = 0
    for a in ACCOUNTS:
        value, metric = followers((a["platform"], a["identifier"]), results)
        if value is None:
            gh_warn(f"Mål — 2026: {a['label']} hoppet over ({metric})")
            skipped += 1
            continue
        p = requests.patch(f"{NOTION_API}/pages/{a['notion_page_id']}", headers=nh(nt),
                           json={"properties": {"Nåverdi": {"number": value}}}, timeout=30)
        p.raise_for_status()
        print(f"UPDATE {a['label']}: {value} | semantic={metric.get('semantic')} | collected_at={metric.get('collected_at')}")
        updated += 1
    print(f"Mål — 2026: updated={updated}, skipped={skipped}")


def meta_selftest():
    """Testmodus: sjekker Meta-kallene for hver Instagram-konto for inneværende
    måned så langt. Skriver ingenting til Notion. Feiler kjøringen hvis noe mangler."""
    today = datetime.now(OSLO).date()
    ms = month_start(today)
    failed = 0
    print(f"=== META-TEST ({month_label(ms)} hittil) – ingenting skrives til Notion ===")
    for ident, secret in IG_TOKEN_SECRETS.items():
        print(f"\n@{ident} ({secret})")
        f, fm = ig_followers(ident)
        print(f"  følgere:       {f if f is not None else 'FEIL – ' + fm}")
        n, nn = ig_net_followers(ident, ms)
        print(f"  netto nye:     {n if n is not None else 'FEIL'} ({nn})")
        if f is not None and n is not None:
            print(f"  startpunkt:    {month_label(prev_month(ms))} ≈ {f - n}")
        r, rn = monthly_unique_reach("instagram", ident, ms)
        print(f"  rekkevidde:    {r if r is not None else 'FEIL'} ({rn})")
        eng = []
        for col, metric_name, summable in IG_ENGAGEMENT:
            v, en = ig_month_total(ident, ms, metric_name, summable)
            print(f"  {col}: {v if v is not None else 'FEIL'} ({en})")
            eng.append(v)
        failed += sum(x is None for x in (f, n, r, *eng))
    print(f"\n=== {'ALT OK' if not failed else f'{failed} FEIL'} ===")
    sys.exit(1 if failed else 0)


def main():
    if os.getenv("TEST_META") == "true":
        meta_selftest()
    mt = need("METRIKA_TOKEN")
    nt = need("NOTION_TOKEN")
    today = datetime.now(OSLO).date()
    target, closing = resolve_target(today)

    results = fetch_metrika(mt)
    update_goals(nt, results)
    problems = update_monthly_tables(nt, results, today, target, closing)

    if closing and problems:
        print(f"ERROR: månedslukking for {month_label(target)} hadde {problems} problem(er) – kjør manuelt med CLOSE_MONTH")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
