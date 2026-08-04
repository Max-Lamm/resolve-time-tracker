LOG := $(HOME)/Library/Logs/resolve-time-tracker.log
DIST_DIR := $(CURDIR)/dist
BUILD_DIR := $(CURDIR)/build
APP_NAME := Resolve Time Tracker
APP_BUNDLE := $(DIST_DIR)/$(APP_NAME).app
DMG_STAGING := $(BUILD_DIR)/dmg-staging

.PHONY: test logs bundle dmg

test:
	uv run pytest -v

logs:
	tail -f $(LOG)

# Eigenstaendiges App-Bundle per PyInstaller (siehe packaging/ResolveTimeTracker.spec),
# nach dem in node-toggle bereits gegen ein echtes Resolve verifizierten Muster.
# Enthaelt einen eigenen Python-Interpreter, braucht also beim Empfaenger weder
# Terminal noch Homebrew noch ein geklontes Repo.
bundle:
	uv run pyinstaller packaging/ResolveTimeTracker.spec --noconfirm \
		--distpath "$(DIST_DIR)" --workpath "$(BUILD_DIR)/pyinstaller"
	@echo "Fertig: $(APP_BUNDLE) -- optional nach /Applications ziehen, oder 'make dmg' fuer die Weitergabe."

# DMG mit App-Bundle und einem Applications-Symlink zum Reinziehen, wie bei
# jeder gewoehnlichen Mac-App-Installation. Kein Fremdtool noetig, hdiutil ist
# Teil von macOS.
dmg: bundle
	rm -rf "$(DMG_STAGING)"
	mkdir -p "$(DMG_STAGING)"
	cp -R "$(APP_BUNDLE)" "$(DMG_STAGING)/"
	ln -s /Applications "$(DMG_STAGING)/Applications"
	rm -f "$(DIST_DIR)/$(APP_NAME).dmg"
	hdiutil create -volname "$(APP_NAME)" -srcfolder "$(DMG_STAGING)" -ov -format UDZO \
		"$(DIST_DIR)/$(APP_NAME).dmg"
	rm -rf "$(DMG_STAGING)"
	@echo "Fertig: $(DIST_DIR)/$(APP_NAME).dmg"
