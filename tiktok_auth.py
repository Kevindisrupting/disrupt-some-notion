"""
Engangsoppsett av TikTok-tilkobling per konto.

1) Åpne innloggingslenken som skrives ut i steg 1 (TT_STEP=link), logg inn på TikTok-kontoen
   og godkjenn. Du havner på redirect-adressen med ?code=... i adressefeltet.
2) Kjør steg 2 (TT_STEP=exchange) med koden. Skriptet bytter koden mot et refresh-token og
   lagrer det direkte som GitHub-secret (TT_REFRESH_DISRUPT / TT_REFRESH_PU). Tokenet vises aldri.
"""
import os
import sys
from urllib.parse import urlencode, urlparse, parse_qs

import requests

sys.path.insert(0, os.path.dirname(__file__))
from update_some_goals import write_github_secret, mask, TT_API  # noqa: E402

ACCOUNT_SECRET = {"disrupt": "TT_REFRESH_DISRUPT", "pu": "TT_REFRESH_PU"}
SCOPES = "user.info.basic,user.info.stats,video.list"


def main():
    ck = os.environ["TT_CLIENT_KEY"]
    redirect = os.environ["TT_REDIRECT_URI"]
    step = os.getenv("TT_STEP", "link")
    account = os.getenv("TT_ACCOUNT", "disrupt").lower()
    if account not in ACCOUNT_SECRET:
        sys.exit(f"Ukjent konto {account!r} – bruk disrupt eller pu")

    if step == "link":
        url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
            "client_key": ck, "scope": SCOPES, "response_type": "code",
            "redirect_uri": redirect, "state": account})
        print(f"Åpne denne lenken og logg inn som {account}-kontoen på TikTok:\n\n{url}\n")
        print("Kopier deretter HELE adressen du havner på (den inneholder ?code=...) og kjør steg 2.")
        return

    raw = os.environ.get("TT_CODE", "").strip()
    code = parse_qs(urlparse(raw).query).get("code", [raw])[0] if raw.startswith("http") else raw
    mask(code)
    r = requests.post(f"{TT_API}/oauth/token/", data={
        "client_key": ck, "client_secret": os.environ["TT_CLIENT_SECRET"], "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect},
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    j = r.json() if r.content else {}
    if not r.ok or "refresh_token" not in j:
        sys.exit(f"Feil fra TikTok: {r.status_code} {j.get('error')} {j.get('error_description')}")
    mask(j["refresh_token"]); mask(j.get("access_token", ""))
    missing = [s for s in ("user.info.stats", "video.list") if s not in (j.get("scope") or "")]
    if missing:
        print(f"ADVARSEL: disse tillatelsene ble ikke godkjent: {', '.join(missing)}")
    if write_github_secret(ACCOUNT_SECRET[account], j["refresh_token"]):
        print(f"Ferdig: {ACCOUNT_SECRET[account]} er lagret i GitHub. Gyldig i 365 dager og fornyes automatisk.")
    else:
        sys.exit("Kunne ikke lagre secret – sjekk GH_SECRETS_PAT.")


if __name__ == "__main__":
    main()
