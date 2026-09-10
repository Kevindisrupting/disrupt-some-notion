# Disrupt — automatisk SoMe → Notion

Kjører hver mandag kl. 07:30 Europe/Oslo og oppdaterer `Nåverdi` direkte på de riktige årlige KPI-radene i Notion.

## Oppsett
1. Lag et privat GitHub-repository, f.eks. `disrupt-some-notion`.
2. Last opp innholdet i denne mappen, inkludert `.github/workflows/update-some-goals.yml`.
3. Gå til `Settings → Secrets and variables → Actions`.
4. Opprett:
   - `METRIKA_TOKEN`
   - `NOTION_TOKEN`
5. Lag en intern Notion integration og gi den tilgang til databasen `Mål — 2026`.
6. Legg integration secret inn som `NOTION_TOKEN`.
7. Gå til `Actions → Update SoMe goals in Notion → Run workflow` for en manuell test.

## Sikkerhet
Ikke legg tokens direkte i scriptet.

## Robusthet
Profiler med `pending`, manglende verdi eller verdi <= 0 blir hoppet over, så Notion overskrives ikke med ugyldige data.

## Facebook
Metrika returnerer `followers`-feltet, men resultatene våre har hatt `semantic=likes`. Scriptet oppdaterer denne verdien og logger semantic-feltet ved hver kjøring.
