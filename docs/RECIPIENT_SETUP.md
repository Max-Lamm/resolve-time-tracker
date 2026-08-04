# Resolve Time Tracker einrichten

Kurzanleitung für alle, die die App zum ersten Mal installieren. Kein Terminal nötig.

## Voraussetzungen

- **macOS auf Apple Silicon** (M1 oder neuer).
- **DaVinci Resolve Studio** — die kostenlose Version von DaVinci Resolve hat kein Scripting, ohne das kann die App nicht mitbekommen, an welchem Projekt du arbeitest.
- Ein **Toggl-Account** (kostenlos unter [toggl.com](https://toggl.com)), falls noch keiner vorhanden ist.

## 1. Installation

1. `Resolve Time Tracker.dmg` öffnen (Doppelklick).
2. Das App-Symbol in den `Applications`-Ordner ziehen, der im selben Fenster daneben liegt.
3. Das DMG-Fenster schließen, das Bild aus dem Finder auswerfen (Rechtsklick → Auswerfen).

## 2. Erster Start: die Sicherheitswarnung

Die App ist noch nicht bei Apple registriert (notariert), deshalb meldet sich macOS beim allerersten Start mit einer Warnung. Das ist einmalig:

1. App in `Applications` **doppelklicken**. Es erscheint eine Meldung, dass die App nicht geöffnet werden kann.
2. **Systemeinstellungen → Datenschutz & Sicherheit** öffnen, dort etwas herunterscrollen. Es steht dort ein Hinweis auf die blockierte App mit einem Knopf **"Trotzdem öffnen"**.
3. Diesen Knopf klicken, im nächsten Dialog noch einmal mit **Öffnen** bestätigen.

Ab jetzt startet die App per Doppelklick ganz normal, ohne weitere Nachfrage.

## 3. Resolve fürs Scripting freischalten

Damit die App überhaupt mitbekommt, was in Resolve passiert, einmalig in Resolve:

**DaVinci Resolve → Preferences (⌘,) → System → General → "External scripting using"** auf **Local** stellen, dann Resolve einmal neu starten.

Läuft Resolve bereits, aber diese Einstellung fehlt noch, erkennt die App das automatisch und zeigt im Menü einen Hinweis mit genau dieser Anleitung.

## 4. Der Einrichtungsassistent

Beim allerersten Start führt die App selbst durch die restliche Einrichtung: eine kurze Begrüßung, ein Hinweis, falls Resolve noch nicht bereit ist, die Abfrage des Toggl-Tokens und die Frage, ob die App künftig automatisch beim Login starten soll. Jeder Schritt lässt sich mit **Abbrechen** überspringen, falls gerade etwas fehlt — das lässt sich später jederzeit über das Menü nachholen (**Einrichtung erneut starten…**).

Den Toggl-Token findest du in Toggl unter **Profil → API Token** (ganz unten auf der Seite), einfach kopieren und in den Dialog einfügen.

## 5. Die App benutzen

Resolve nimmt in der Menüleiste viel Platz ein, deshalb zeigt der Tracker dort nur ein kleines farbiges Symbol: 🟢 während getrackt wird, 🟡 bei kurzer Pause, ⚪ wenn gerade nichts läuft. Klick drauf öffnet das ganze Menü mit Projekt-Zuordnung, manueller Pause, Sync-Status und den Einstellungen.

## Problembehebung

- **Menü zeigt "Resolve laeuft nicht"**, obwohl Resolve offen ist: Schritt 3 oben nachholen (External Scripting auf Local).
- **Menü zeigt "Resolve-Scripting nicht aktiviert"**: derselbe Schritt, Resolve danach neu starten.
- Für alles andere: Menü → **Log oeffnen** zeigt die Logdatei mit Details.
