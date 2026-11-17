# fhbook — FH-Moodle & Giancoli für Claude lesbar machen

MCP-Server, mit dem Claude (Claude Code / Claude Desktop) die Lernpfade im FH-Technikum-Moodle
und das Pearson-E-Book **Giancoli: Physik** lesen kann — zum Lernen, Erklären lassen und Mitschriften verbessern.

**So funktioniert's:** fhbook öffnet ein eigenes Firefox-Fenster (sieht aus wie „Firefox Nightly“).
Du loggst dich dort **selbst** in Moodle ein. Claude liest und navigiert dann in genau diesem Fenster —
deine Zugangsdaten gehen nie durch das Tool, und es funktioniert nur mit deiner eigenen Lizenz.

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) (installiert Python-Abhängigkeiten automatisch)
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Claude Code oder Claude Desktop

## Installation

```sh
git clone <repo-url> ~/fhbook
uvx playwright install firefox        # einmalig, lädt den Browser (~100 MB)
```

**Claude Code:**

```sh
claude mcp add fhbook -s user -- uv run --script ~/fhbook/fhbook_mcp.py
```

**Claude Desktop** (`claude_desktop_config.json`, Pfad anpassen):

```json
{
  "mcpServers": {
    "fhbook": { "command": "uv", "args": ["run", "--script", "/ABSOLUTER/PFAD/fhbook/fhbook_mcp.py"] }
  }
}
```

Claude danach neu starten.

## Benutzung

1. Zu Claude sagen: „Starte fhbook“ → das Nightly-Fenster geht auf.
2. Im Fenster selbst bei Moodle einloggen und den Kurs öffnen. **Fenster offen lassen** (minimieren ist ok).
3. Dann z. B.:
   - „Geh den Lernpfad Vorbereitung 3 durch und fass zusammen.“
   - „Öffne Giancoli Kapitel 7.1–7.4 und erklär mir das Skalarprodukt.“
   - „Hier meine Mitschrift zu Kapitel 4 — gleich sie mit dem Giancoli ab und ergänze, was fehlt.“

Giancoli-Kapitel immer über den Lernpfad-Link („Giancoli: Kapitel …“) öffnen — kopierte Pearson-Links
haben keine Lizenz und zeigen nur Schlösser.

Fenster geschlossen → Login weg, neu starten und wieder einloggen.

Fehlt Playwrights Firefox (z. B. nach einem Update), installiert `start` ihn beim ersten Start automatisch nach.

## Tools

| Tool | Zweck |
|---|---|
| `start_browser` | Fenster öffnen |
| `read_page`, `list_links`, `click`, `goto`, `back`, `tabs`, `switch_tab` | Moodle/Lernpfade navigieren |
| `screenshot` | Formeln, Abbildungen |
| `download` | Moodle-Dateien (PDFs) mit der Browser-Session speichern — per URL, Linktext oder aktuellem Tab |
| `book_info`, `book_read_pages`, `book_search`, `book_goto_page` | Giancoli-PDF (ein PDF pro Kapitel) |
| `run_js` | Notnagel für ungewöhnliche Seiten |

Ohne Claude geht's auch per CLI: `uv run --script fhbook.py start` / `read` / `links Giancoli` / `click "Kapitel 7"`.

## Konfiguration (optional, Umgebungsvariablen)

- `FHBOOK_PORT` (Standard 9334) — lokaler Port, nur `127.0.0.1`
- `FHBOOK_PROFILE` — Browser-Profilordner
- `FHBOOK_START_URL` — Startseite (Standard: FH-Technikum-Moodle)
- `FHBOOK_DOWNLOADS` — Zielordner für `download` (Standard `~/Downloads/fhbook`)

## Hinweise

- Nur für den persönlichen Lerngebrauch mit eigenem Zugang. Buchinhalte nicht massenhaft exportieren
  oder weitergeben — das verbieten Urheberrecht und die Pearson-Nutzungsbedingungen.
- Laut Kurs-Infos ist KI beim Lernen erlaubt, bei Prüfungen/Leistungsbeurteilungen nur mit ausdrücklicher Erlaubnis.
- Die lokale HTTP-Schnittstelle lauscht nur auf `127.0.0.1`, kann aber den eingeloggten Browser steuern —
  auf geteilten Rechnern nicht laufen lassen.
