LABEL := com.monacoframe.resolve-time-tracker
PLIST := $(HOME)/Library/LaunchAgents/$(LABEL).plist
LOG := $(HOME)/Library/Logs/resolve-time-tracker.log
PYTHON := $(CURDIR)/.venv/bin/python
DIST_DIR := $(CURDIR)/dist
APP_NAME := Resolve Time Tracker
APP_BUNDLE := $(DIST_DIR)/$(APP_NAME).app

.PHONY: test install uninstall logs app

test:
	uv run pytest -v

$(PYTHON):
	uv sync

install: $(PYTHON)
	mkdir -p $(HOME)/Library/LaunchAgents
	sed -e 's|__PYTHON__|$(PYTHON)|g' -e 's|__LOG__|$(LOG)|g' \
		packaging/$(LABEL).plist > $(PLIST)
	-launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null
	launchctl bootstrap gui/$$(id -u) $(PLIST)
	@echo "Installiert. Naechster Schritt: uv run rtt token"

uninstall:
	-launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null
	rm -f $(PLIST)
	@echo "Deinstalliert. Datenbank und Config bleiben erhalten."

logs:
	tail -f $(LOG)

# Handgebautes .app-Bundle, keine Drittanbieter-Tools noetig: ein .app ist
# nur ein Ordner mit einem ausfuehrbaren Skript und einem Info.plist.
# LSUIElement im Plist sorgt fuer kein Dock-Icon (reine Menubar-App), so wie
# es rumps fuer per py2app gebaute Apps ebenfalls empfiehlt.
app: $(PYTHON)
	rm -rf "$(APP_BUNDLE)"
	mkdir -p "$(APP_BUNDLE)/Contents/MacOS"
	sed 's|__PYTHON__|$(PYTHON)|g' packaging/launch_menubar.sh > "$(APP_BUNDLE)/Contents/MacOS/ResolveTimeTracker"
	chmod +x "$(APP_BUNDLE)/Contents/MacOS/ResolveTimeTracker"
	cp packaging/Info.plist "$(APP_BUNDLE)/Contents/Info.plist"
	@echo "Fertig: $(APP_BUNDLE) -- optional nach /Applications ziehen."
