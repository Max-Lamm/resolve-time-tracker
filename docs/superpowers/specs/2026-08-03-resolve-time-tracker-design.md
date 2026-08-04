# Resolve Time Tracker — Design

## Context

Arbeitszeit pro Projekt wird aktuell nicht systematisch erfasst. Manuelles Starten und Stoppen von Timern scheitert im Alltag daran, dass man es vergisst, und klassische Tracker lassen die Uhr weiterlaufen, während man telefoniert oder Kaffee holt. Ergebnis: entweder gar keine Zahlen oder aufgeblasene.

Ziel ist ein Hintergrund-Dienst, der aus DaVinci Resolve Studio heraus automatisch erfasst, an welchem Projekt wie lange tatsächlich gearbeitet wurde, Pausen herausrechnet und fertige Zeiten nach Toggl schiebt. Referenz für den Funktionsumfang ist https://www.jamiefenn.com/timetracker/, allerdings dort als Skript im Resolve-Prozess. Hier wird bewusst ein eigenständiger Daemon gebaut, weil das robuster ist und Idle über echte macOS-Systemsignale messen kann.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Resolve-Variante | Nur Studio, externes Scripting erlaubt |
| Form | macOS-Menubar-App, Python + `rumps`, per launchd beim Login |
| Toggl | Lokale SQLite ist Wahrheit, fertige Einträge werden gepusht |
| Aktiv-Definition | Resolve ist vorderste App UND Input kürzlich (Playback-Signal per Live-Test verworfen, siehe unten) |
| Projekt-Zuordnung | Mapping-Tabelle, unbekannte Projekte werden lokal getrackt und geparkt |

## Verifizierte technische Grundlagen

- Externes Scripting funktioniert nur in Resolve **Studio**, Resolve muss laufen. Die freie Version kann nur Skripte im eigenen Prozess ausführen.
- macOS-Umgebung: `RESOLVE_SCRIPT_API=/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting`, `RESOLVE_SCRIPT_LIB=/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so`, `PYTHONPATH` um `$RESOLVE_SCRIPT_API/Modules/` erweitern. Einstieg über `DaVinciResolveScript.scriptapp("Resolve")`.
- Die API kennt **keine Events**, nur Polling. `GetCurrentPage()` liefert `media|cut|edit|fusion|color|fairlight|deliver|None`.
- Toggl Track API v9: `POST https://api.track.toggl.com/api/v9/workspaces/{workspace_id}/time_entries`, Basic Auth mit API-Token als Username und dem Literal `api_token` als Passwort. Pflichtfeld `created_with`. Fertige Einträge über `start` plus positive `duration` in Sekunden. Rate Limit: sicher sind 1 Request pro Sekunde, sonst HTTP 429.
- Idle und Frontmost-App gehen über pyobjc ohne Accessibility-Berechtigung: `Quartz.CGEventSourceSecondsSinceLastEventType` und `AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()`.

## Schritt 0: Machbarkeits-Smoke-Test (blockierend, zuerst)

Die Python-Anbindung an Resolve ist auf macOS historisch die zickigste Stelle des ganzen Projekts (`fusionscript.so` gegen eine bestimmte Python-Version gebaut). Vor allem anderen ein Wegwerf-Skript `scripts/smoke_resolve.py`, das bei laufendem Resolve ausgibt:

- Verbindung steht, Projektname, Datenbankname
- `GetCurrentPage()`
- Timeline-Name und `GetCurrentTimecode()`, **zweimal im Abstand von 2 Sekunden während laufendem Playback**, um zu prüfen ob sich der Timecode wirklich fortschreibt
- Dauer eines Poll-Zyklus in Millisekunden

Damit stehen drei Dinge fest: welche Python-Version funktioniert, ob die Playback-Erkennung überhaupt möglich ist, und wie teuer ein Tick ist. Fällt der Timecode-Test durch, entfällt das Playback-Signal und `is_active` stützt sich nur auf Input. Das ist eine akzeptable Abwertung, muss aber vorher bekannt sein.

**Ergebnis des Live-Tests (2026-08-04, gegen echtes Resolve Studio):** Verbindung, Projektname, Datenbank, Page und Timeline werden zuverlässig gelesen, Poll-Kosten liegen bei ca. 3,3 ms pro Zyklus. `GetCurrentTimecode()` bewegt sich während laufender Wiedergabe jedoch **nicht** zuverlässig, das ist eine bekannte Einschränkung der Resolve-Scripting-API: der Wert reflektiert die Playhead-Position bei Pause/Scrub, aktualisiert sich aber nicht in Echtzeit während aktiver Wiedergabe. Das Playback-Signal entfällt deshalb vollständig. `is_active` prüft ab jetzt ausschließlich Input-Aktualität, solange Resolve vorne ist. `ResolveSnapshot.timecode` bleibt als informatives Feld erhalten (zur Anzeige/Diagnose), fließt aber in keine Aktivitätsentscheidung mehr ein, und der Adapter poll't es nicht mehr selektiv nur wenn Resolve vorne ist (der Grund für diese Optimierung, Kosten für die Aktivitätsprüfung sparen, ist entfallen).

## Architektur

Ein Prozess, ein 5-Sekunden-Tick, klar getrennte Module. Die Trennlinie ist überall dieselbe: alles was mit der Außenwelt redet, ist ein dünner Adapter, die Entscheidungslogik ist rein und ohne I/O.

```
src/resolve_time_tracker/
  resolve_probe.py   Adapter Resolve-API  -> ResolveSnapshot
  activity.py        Adapter macOS        -> idle_seconds, frontmost_bundle_id
  tracker.py         reine Zustandsmaschine (Kern, TDD)
  store.py           SQLite, append-only Segmente
  toggl.py           Adapter Toggl-API
  syncer.py          Segmente -> Toggl-Einträge
  config.py          TOML + Keychain
  menubar.py         rumps-UI, dünn
  __main__.py        Tick-Loop, verdrahtet alles
```

### `resolve_probe.py`
Kapselt jeden Resolve-Aufruf. Liefert ein `ResolveSnapshot`-Dataclass: `connected`, `project_name`, `database_name`, `page`, `timeline_name`, `timecode`. Jeder Fehlerfall (Resolve zu, kein Projekt offen, API wirft) wird zu `connected=False` statt zu einer Exception. Der Timecode wird nur gepollt, wenn Resolve vorne ist, das spart den teuersten Call.

### `activity.py`
Zwei Funktionen, kein Resolve-Wissen: `seconds_since_input()` und `frontmost_bundle_id()`. Resolve-Bundle-IDs beginnen mit `com.blackmagic-design.DaVinciResolve`, Präfix-Match, damit Studio und Nicht-Studio-Builds beide greifen.

### `tracker.py` (Herzstück)
Nimmt pro Tick ein `Tick(now, snapshot, idle_seconds, frontmost)` und gibt Kommandos zurück (`OpenSegment`, `TouchSegment`, `CloseSegment(cut_to=...)`). Kein Datenbankzugriff, keine echte Uhr, `now` wird hereingereicht. Dadurch komplett per TDD in Millisekunden testbar.

Aktivitätsregel pro Tick, `is_active` nur wenn alles zutrifft:
1. `snapshot.connected` und `project_name` gesetzt
2. `frontmost` ist Resolve
3. `idle_seconds < input_grace` (Standard 30 s)

(Das ursprünglich vorgesehene Playback-Signal, Timecode-Änderung als Alternative zu Input, entfiel nach dem Live-Test in Schritt 0, siehe oben.)

Zustände: `NO_RESOLVE`, `ACTIVE`, `PENDING_IDLE`, `PAUSED_IDLE`, `PAUSED_MANUAL`.

Der rückwirkende Kniff: Ein offenes Segment führt ein `last_active_at`. Wird `is_active` falsch, wechselt der Tracker nach `PENDING_IDLE` und lässt das Segment offen. Kommt innerhalb von `idle_threshold` (Standard 5 min) wieder Aktivität, läuft es einfach weiter und die Lücke zählt mit, das sind Denkpausen. Bleibt es länger still, wird das Segment **auf `last_active_at` zurückgeschnitten** und geschlossen. So wird nie zu viel gezählt, und der Rückschnitt braucht keine Toggl-Korrektur, weil noch nichts gepusht wurde.

Wechselt `project_name`, wird das laufende Segment geschlossen und ein neues geöffnet.

### `store.py`
SQLite unter `~/Library/Application Support/resolve-time-tracker/tracker.db`, WAL-Modus.

- `segments`: `id`, `resolve_project`, `resolve_database`, `started_at`, `last_active_at`, `ended_at` (NULL solange offen), `pages_seen` (JSON-Set), `note`, `toggl_entry_id`, `synced_at`
- `project_map`: `resolve_project` → `toggl_workspace_id`, `toggl_project_id`
- `meta`: Schema-Version

`last_active_at` wird bei jedem Tick fortgeschrieben. Stirbt der Daemon hart, begrenzt der nächste Start jedes noch offene Segment automatisch auf seinen letzten bekannten Aktiv-Zeitpunkt. Crash kostet also höchstens 5 Sekunden, nie eine ganze Nacht.

### `syncer.py`
Pushbar ist ein Segment, wenn es geschlossen ist, `toggl_entry_id IS NULL`, ein `project_map`-Eintrag existiert, und es länger als `merge_gap` (Standard 10 min) zurückliegt. Vor dem Push werden Segmente desselben Resolve-Projekts, die weniger als `merge_gap` auseinanderliegen, zu einem Toggl-Eintrag verschmolzen, sonst entstehen 40 Schnipsel pro Tag. Beschreibung ist der Resolve-Projektname plus Notiz, Tags sind die berührten Resolve-Pages. Nach Erfolg wird `toggl_entry_id` gesetzt, das ist die Idempotenz-Sperre. Requests werden auf 1/Sekunde gedrosselt, 429 und Netzfehler führen zu Zurückstellen, nie zu Datenverlust.

Segmente ohne `project_map`-Eintrag bleiben ungepusht liegen und werden in der Menubar als „nicht zugeordnet" gemeldet. Nach nachträglicher Zuordnung gehen sie automatisch mit raus.

### `menubar.py`
Titel: `● 2:14 Projektname` aktiv, `○ 2:14` pausiert, `–` wenn Resolve zu. Menü: Heute gesamt, aktuelles Projekt heute, Pause/Fortsetzen, „Nicht zugeordnet (n)" mit Zuordnungsdialog gegen die Toggl-Projektliste, „Jetzt synchronisieren", Log öffnen, Beenden.

### `config.py`
TOML unter `~/.config/resolve-time-tracker/config.toml` für Schwellwerte und Mapping-Defaults. Der Toggl-API-Token gehört **nicht** in die Datei, sondern über `keyring` in die macOS-Keychain, gesetzt per CLI-Unterbefehl.

## Betrieb

LaunchAgent `~/Library/LaunchAgents/com.monacoframe.resolve-time-tracker.plist` mit `RunAtLoad` und `KeepAlive`, die drei Resolve-Umgebungsvariablen in `EnvironmentVariables`, Logs nach `~/Library/Logs/resolve-time-tracker.log` mit Rotation. Installation über ein `make install`-Ziel, nicht per Hand zusammengeklickt.

## Tests

- `tracker.py`: der Schwerpunkt, TDD, synthetische Tick-Sequenzen ohne echte Uhr. Abgedeckte Fälle: durchgehende Arbeit, kurze Pause unter Schwelle (zählt mit), lange Pause (Rückschnitt), Projektwechsel mitten in der Arbeit, Resolve wird beendet während ein Segment offen ist, Resolve läuft im Hintergrund während in Mail gearbeitet wird (inaktiv), manuelle Pause überstimmt alles.
- `store.py`: gegen temporäre SQLite, inklusive Wiederanlauf mit offenem Segment.
- `syncer.py`: Verschmelzungslogik und Idempotenz gegen einen Fake-Toggl-Client.
- `toggl.py`: gegen aufgezeichnete HTTP-Antworten (`responses`), inklusive 429-Pfad.
- `resolve_probe.py` und `activity.py`: keine Unit-Tests, das sind Adapter. Verifikation über den Smoke-Test aus Schritt 0.

## Verifikation Ende-zu-Ende

1. `scripts/smoke_resolve.py` bei laufendem Resolve. (Bereits durchgeführt, siehe Ergebnis oben: Playback-Signal entfällt.)
2. `pytest` grün.
3. Daemon im Vordergrund starten, Resolve öffnen, ein Projekt laden. Menubar zeigt Projektnamen und laufende Zeit.
4. Fünf Minuten in Mail arbeiten, zurückkommen. In der DB muss das Segment auf den Zeitpunkt vor dem Wechsel zurückgeschnitten sein, nicht durchlaufen.
5. Projekt in Resolve wechseln. Zwei getrennte Segmente in der DB.
6. Toggl-Push gegen einen Testworkspace, danach der Eintrag in Toggl mit korrekter Dauer, Projekt und Tags. Zweiter Push-Lauf legt keinen Duplikat-Eintrag an.
7. Daemon während offenem Segment mit `kill -9` beenden, neu starten. Das Segment ist sauber begrenzt, keine Endlosdauer.

## Bewusst nicht dabei (YAGNI)

Keine Stundensätze und Rechnungslogik (macht Toggl), kein Web-Dashboard, keine Windows-Unterstützung, keine Unterstützung der freien Resolve-Version, kein CSV-Export (Toggl kann das), keine Zeiterfassung für andere Apps.
