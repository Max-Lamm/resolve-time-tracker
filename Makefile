LABEL := com.monacoframe.resolve-time-tracker
PLIST := $(HOME)/Library/LaunchAgents/$(LABEL).plist
LOG := $(HOME)/Library/Logs/resolve-time-tracker.log
PYTHON := $(CURDIR)/.venv/bin/python

.PHONY: test install uninstall logs

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
