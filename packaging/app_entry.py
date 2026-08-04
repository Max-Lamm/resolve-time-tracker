"""Einstiegspunkt fuer das PyInstaller-Bundle.

Ruft cli.main() mit einem festen Argument statt sys.argv zu parsen: macOS
haengt einem per Doppelklick gestarteten Bundle mitunter eigene Argumente an
(z. B. ein Prozess-Serial-Number-Flag auf aelteren Systemen), die argparse
sonst als unbekanntes Kommando ablehnen wuerde. Single-Instance-Lock und der
native "laeuft bereits"-Hinweis bleiben ueber cmd_menubar() erhalten (siehe
cli.py), es wird hier bewusst nichts davon dupliziert.
"""

from resolve_time_tracker.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["menubar"]))
