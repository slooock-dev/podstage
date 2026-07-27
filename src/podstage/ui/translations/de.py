"""German (de) translation catalog. Keys are the English source strings.

Only entries that actually differ from the English source are listed; where a
term is identical in both languages (Session, Setup, Start, Stop, Client, Port,
Login, Pause, Backend …) the English fallback already yields correct German.
Referenced page/button names use »…« guillemets, matching the code style.
"""


TEXTS: dict[str, str] = {
    # -- app shell / global state ----------------------------------------
    "○ stopped": "○ gestoppt",
    "● running": "● läuft",
    "Sandboxes": "Sandboxen",
    "Quit podstage?": "podstage beenden?",
    "A streaming session is running{owner}. Quitting stops the container and "
    "ends the stream.\n\nStop it and quit?":
        "Eine Streaming-Session läuft{owner}. Beim Beenden wird der Container "
        "gestoppt und der Stream beendet.\n\nStoppen und beenden?",

    # -- logs page -------------------------------------------------------
    "Clear": "Leeren",
    "Resume": "Weiter",

    # -- session page ----------------------------------------------------
    "Pair …": "Pairen …",
    "Pair a new Moonlight client by PIN (session must be running)":
        "Neuen Moonlight-Client per PIN pairen (Session muss laufen)",
    "Game": "Spiel",
    "Preview": "Vorschau",
    "Refresh every": "Aktualisieren alle",
    "How often the in-container preview is captured; 0 turns it off. Applies "
    "from the next stream start.":
        "Wie oft die Vorschau im Container aufgenommen wird; 0 schaltet sie aus. "
        "Wirkt ab dem nächsten Stream-Start.",
    "Preview appears here while streaming.":
        "Die Vorschau erscheint hier während des Streams.",
    "No preview with the {backend} backend.":
        "Kein Vorschaubild mit dem Backend {backend}.",
    "Preview is off": "Vorschau ist aus",
    "waiting for preview …": "warte auf Vorschau …",
    "no new frames": "keine neuen Frames",
    "Stream quality": "Stream-Qualität",
    "NVENC preset": "NVENC-Preset",
    "Apply live": "Live übernehmen",
    "Apply immediately to the running session (stream briefly reconnects)":
        "Auf die laufende Session sofort anwenden (Stream verbindet kurz neu)",
    "Bitrate & codec are chosen by the Moonlight client; these control encoder "
    "quality on the server side.":
        "Bitrate & Codec wählt der Moonlight-Client; diese steuern die "
        "Encoder-Qualität serverseitig.",
    "The {backend} backend has no server-side quality settings; the Moonlight "
    "client picks bitrate and codec.":
        "Das Backend {backend} hat keine serverseitigen Qualitätseinstellungen; "
        "Bitrate und Codec wählt der Moonlight-Client.",
    "The {backend} backend has no live quality settings; these apply to "
    "Sunshine profiles only.":
        "Das Backend {backend} hat keine Qualitätseinstellungen zur Laufzeit; "
        "diese gelten nur für Sunshine-Profile.",
    "VBV buffer increase (%): a larger buffer reduces artifacts in fast motion "
    "at the same bitrate. 0 = Sunshine default.":
        "VBV-Puffer-Erhöhung (%): ein größerer Puffer reduziert Artefakte bei "
        "schnellen Bewegungen bei gleicher Bitrate. 0 = Sunshine-Standard.",
    "Open Sunshine web UI": "Sunshine Web-UI öffnen",
    "Saved. Applies from the next stream start; use 'Apply live' for a "
    "running session.":
        "Gespeichert. Gilt ab dem nächsten Stream-Start; »Live übernehmen« "
        "wendet es auf eine laufende Session an.",
    "starting …": "startet …",
    "stopping …": "stoppt …",
    "Error": "Fehler",
    "Big Picture / menu": "Big Picture / Menü",
    "{n} session(s)": "{n} Session(s)",
    "'{name}' is not set up. Start the Steam login on the 'Sandboxes' page.":
        "'{name}' ist nicht eingerichtet. Steam-Login auf der Seite "
        "»Sandboxen« starten.",
    "Starting container (provisioning + podman) …":
        "Container wird gestartet (Provisionierung + podman) …",
    "'{name}' picks its resolution at startup.\nResolution for this session:":
        "'{name}' wählt seine Auflösung beim Start.\nAuflösung für diese "
        "Session:",
    "The PIN was submitted but no pairing completed. Restart the pairing in "
    "Moonlight and enter the new PIN.":
        "Die PIN wurde übermittelt, aber kein Pairing abgeschlossen. Pairing "
        "in Moonlight neu starten und die neue PIN eintragen.",
    "Client '{name}' paired. Moonlight can stream now.":
        "Client '{name}' gepairt. Moonlight kann jetzt streamen.",
    "Paired. Moonlight can stream now.":
        "Gepairt. Moonlight kann jetzt streamen.",
    "Pairing failed: {msg}": "Pairing fehlgeschlagen: {msg}",
    "Applying live … (stream briefly interrupts)":
        "Wende live an … (Stream unterbricht kurz)",
    "Applied live. The stream is reconnecting.":
        "Live angewendet. Der Stream verbindet sich neu.",
    "No running session. The setting is saved and applies from the next start.":
        "Keine laufende Session. Die Einstellung ist gespeichert und gilt ab "
        "dem nächsten Start.",
    "Saved; live apply failed: {msg}":
        "Gespeichert; Live-Anwendung fehlgeschlagen: {msg}",

    # -- pair dialog -----------------------------------------------------
    "Pair client": "Client pairen",
    "PIN from Moonlight, e.g. 1234": "PIN aus Moonlight, z. B. 1234",
    "Device name": "Gerätename",
    "Select the server in Moonlight and enter the 4-digit PIN it shows here.":
        "In Moonlight den Server auswählen und die angezeigte 4-stellige "
        "PIN hier eintragen.",

    # -- Sunshine web UI dialog ------------------------------------------
    "Sunshine web UI": "Sunshine Web-UI",
    "User": "Benutzer",
    "Password": "Passwort",
    "Copy password": "Passwort kopieren",
    "Open in browser": "Im Browser öffnen",
    "Close": "Schließen",

    # -- NVENC quality presets ------------------------------------------
    "fastest encoding (default)": "schnellste Kodierung (Standard)",
    "faster": "schneller",
    "fast": "schnell",
    "balanced": "ausgewogen",
    "slow": "langsam",
    "slower": "langsamer",
    "best quality": "beste Qualität",
    "off": "aus",
    "quarter resolution (default)": "Viertel-Auflösung (Standard)",
    "full resolution": "volle Auflösung",

    # -- VAAPI quality (AMD/Intel) --------------------------------------
    "VAAPI quality": "VAAPI-Qualität",
    "Rate control": "Ratensteuerung",
    "Strict RC buffer": "Strikter RC-Puffer",
    "auto (default)": "auto (Standard)",
    "speed": "Geschwindigkeit",
    "quality": "Qualität",
    "variable bitrate": "variable Bitrate",
    "constant bitrate": "konstante Bitrate",
    "constant quality (QP)": "konstante Qualität (QP)",
    "intelligent constant quality": "intelligente konstante Qualität",
    "quality-defined VBR": "qualitätsdefiniertes VBR",
    "average VBR": "durchschnittliches VBR",
    "VAAPI quality profile: the encoder's speed/quality tradeoff.":
        "VAAPI-Qualitätsprofil: Abwägung zwischen Geschwindigkeit und Qualität "
        "des Encoders.",
    "VAAPI rate-control mode. 'auto' lets the driver choose; not every "
    "mode is supported on every GPU.":
        "VAAPI-Ratensteuerung. »auto« überlässt die Wahl dem Treiber; nicht "
        "jeder Modus wird von jeder GPU unterstützt.",
    "Avoids dropped frames over the network during scene changes, but "
    "quality may drop during motion.":
        "Vermeidet verworfene Frames über das Netzwerk bei Szenenwechseln, "
        "die Qualität kann bei Bewegung aber sinken.",

    # -- sandbox page: table + buttons ----------------------------------
    "Steam sandboxes": "Steam-Sandboxen",
    "Resolution": "Auflösung",
    "Size": "Größe",
    "New …": "Neu …",
    "Edit …": "Bearbeiten …",
    "Delete …": "Löschen …",
    "Start Steam login": "Steam-Login starten",
    "Clear overlay …": "Overlay leeren …",
    "Discards this sandbox's writes onto the shared game libraries (game "
    "updates re-apply in the next session). Host libraries and the sandbox "
    "HOME are untouched.":
        "Verwirft die Schreibzugriffe dieser Sandbox auf die geteilten "
        "Spiele-Bibliotheken (Spiel-Updates werden in der nächsten Session neu "
        "angewendet). Host-Bibliotheken und Sandbox-HOME bleiben unberührt.",
    "Clear overlay?": "Overlay leeren?",
    "Discard '{name}'s writes onto the shared game libraries ({size})? Game "
    "updates applied in a session are lost and re-apply next time; the host "
    "libraries and the sandbox HOME are untouched.":
        "Die Schreibzugriffe von '{name}' auf die geteilten "
        "Spiele-Bibliotheken verwerfen ({size})? In einer Session angewendete "
        "Spiel-Updates gehen verloren und werden beim nächsten Mal neu "
        "angewendet; Host-Bibliotheken und Sandbox-HOME bleiben unberührt.",
    "Overlay of '{name}' cleared.": "Overlay von '{name}' geleert.",
    "Pick at startup": "Beim Start wählen",
    "✓ logged in": "✓ eingeloggt",
    "— empty": "— leer",
    "✗ no login": "✗ kein Login",
    "Setup: 'Streamed login' signs in over the stream (QR code, no "
    "window on the host). 'Start Steam login' opens the isolated "
    "Steam visibly on the desktop instead, useful for settings Big "
    "Picture does not expose. Either way the game library is "
    "provisioned automatically afterwards.":
        "Einrichtung: »Gestreamter Login« loggt sich über den Stream ein "
        "(QR-Code, kein Fenster auf dem Host). »Steam-Login starten« öffnet "
        "stattdessen das isolierte Steam sichtbar auf dem Desktop, nützlich "
        "für Einstellungen, die Big Picture nicht anbietet. In beiden Fällen "
        "wird die Spiele-Bibliothek danach automatisch provisioniert.",
    "Streamed login": "Gestreamter Login",
    "Extra mounts": "Zusätzliche Mounts",
    "Invalid extra mount": "Ungültiger Mount",
    "One host directory per line, mounted into the session at the "
    "same path (start its games via non-Steam shortcuts in Big "
    "Picture). Default is a read-only overlay like the Steam "
    "libraries; append ':rw' for launchers that update themselves "
    "in place.":
        "Ein Host-Verzeichnis pro Zeile, wird unter demselben Pfad in die "
        "Session gemountet (Spiele darin über Non-Steam-Shortcuts in Big "
        "Picture starten). Standard ist ein read-only-Overlay wie bei den "
        "Steam-Bibliotheken; ':rw' anhängen für Launcher, die sich selbst "
        "aktualisieren.",
    "Boots this sandbox into Big Picture's Steam sign-in over the "
    "stream (QR code via the Steam Mobile App, or the on-screen "
    "keyboard). No window opens on the host.":
        "Startet diese Sandbox direkt in Steams Big-Picture-Anmeldung über "
        "den Stream (QR-Code per Steam-Mobile-App oder Bildschirmtastatur). "
        "Auf dem Host öffnet sich kein Fenster.",
    "The sandbox\n{home}\nboots into Big Picture's Steam sign-in over "
    "the stream: connect with Moonlight and log in with the QR code "
    "(Steam Mobile App) or the on-screen keyboard.\n\nContinue?":
        "Die Sandbox\n{home}\nstartet in Steams Big-Picture-Anmeldung über "
        "den Stream: mit Moonlight verbinden und per QR-Code (Steam-Mobile-"
        "App) oder Bildschirmtastatur einloggen.\n\nFortfahren?",
    "Starting login session …": "Starte Login-Session …",
    "Login session failed: {msg}": "Login-Session fehlgeschlagen: {msg}",
    "Login session running: connect with Moonlight and sign in. "
    "Stop the session on the Session page when you are done; the "
    "next regular start provisions the game library.":
        "Login-Session läuft: mit Moonlight verbinden und einloggen. "
        "Danach die Session auf der Session-Seite stoppen; der nächste "
        "normale Start provisioniert die Spiele-Bibliothek.",

    # -- sandbox page: profile dialog -----------------------------------
    "Edit profile": "Profil bearbeiten",
    "New profile": "Neues Profil",
    "custom": "benutzerdefiniert",
    "e.g. deck, laptop, livingroom": "z. B. deck, laptop, wohnzimmer",
    "WidthxHeight@Hz, e.g. 1920x1080@60": "BreitexHöhe@Hz, z. B. 1920x1080@60",
    "Moonlight port": "Moonlight-Port",
    "Backend": "Backend",
    "Sunshine (default) works on every supported GPU. moonshine brings "
    "its own compositor and encodes with Vulkan Video, which needs an "
    "NVIDIA RTX, AMD RDNA2+ or Intel Arc GPU; it has no live quality "
    "settings and no preview picture. Check with 'podstage doctor'.":
        "Sunshine (Standard) läuft auf jeder unterstützten GPU. moonshine "
        "bringt einen eigenen Compositor mit und kodiert per Vulkan Video, "
        "was eine NVIDIA RTX, AMD RDNA2+ oder Intel Arc voraussetzt; es hat "
        "keine Qualitätseinstellungen zur Laufzeit und kein Vorschaubild. "
        "Prüfen mit 'podstage doctor'.",
    "Needs a GPU with Vulkan video encode (NVIDIA RTX, AMD RDNA2+, "
    "Intel Arc) and its own image "
    "('podstage runtime build --backend moonshine'). No live "
    "quality settings and no preview picture.":
        "Braucht eine GPU mit Vulkan-Video-Encode (NVIDIA RTX, AMD RDNA2+, "
        "Intel Arc) und ein eigenes Image "
        "('podstage runtime build --backend moonshine'). Keine "
        "Qualitätseinstellungen zur Laufzeit und kein Vorschaubild.",
    "Games in this sandbox": "Spiele in dieser Sandbox",
    "Include every installed game (and any you add later)":
        "Alle installierten Spiele einschließen (auch später hinzugefügte)",
    "Filter games …": "Spiele filtern …",
    "No installed games found. Log in to the "
    "sandbox's Steam first.":
        "Keine installierten Spiele gefunden. Logge dich zuerst in das Steam "
        "der Sandbox ein.",
    "All {total} games included.": "Alle {total} Spiele einbezogen.",
    "{n} of {total} games selected.": "{n} von {total} Spielen ausgewählt.",
    "Invalid name": "Ungültiger Name",
    "Only letters, digits, '-' and '_' are allowed "
    "(must start with a letter or digit).":
        "Nur Buchstaben, Ziffern, '-' und '_' erlaubt "
        "(muss mit Buchstabe oder Ziffer beginnen).",
    "Name taken": "Name vergeben",
    "A profile '{name}' already exists.": "Ein Profil '{name}' existiert bereits.",
    "Invalid resolution": "Ungültige Auflösung",
    "Format: WidthxHeight@Hz, e.g. 1920x1080@60":
        "Format: BreitexHöhe@Hz, z. B. 1920x1080@60",
    "Port in use": "Port belegt",
    "Port {port} is already used by profile '{name}'.":
        "Port {port} nutzt bereits das Profil '{name}'.",

    # -- sandbox page: delete dialog ------------------------------------
    "Delete '{name}'": "'{name}' löschen",
    "Remove only the profile (keep sandbox data)":
        "Nur das Profil entfernen (Sandbox-Daten behalten)",
    "Delete profile AND sandbox data: {home} ({size})":
        "Profil UND Sandbox-Daten löschen: {home} ({size})",
    "Type '{name}' to confirm": "Zum Bestätigen '{name}' eintippen",
    "The sandbox holds a logged-in Steam account, settings and save games for "
    "this client.":
        "Die Sandbox enthält einen eingeloggten Steam-Account, Einstellungen "
        "und Spielstände dieses Clients.",

    # -- sandbox page: status messages ----------------------------------
    "Profile '{name}' created. Now use 'Start Steam login' to set it up.":
        "Profil '{name}' angelegt. Jetzt »Steam-Login starten« für die "
        "Einrichtung.",
    "No profile selected.": "Kein Profil ausgewählt.",
    "Profile '{name}' saved.": "Profil '{name}' gespeichert.",
    "Stop the running session first.": "Die laufende Session erst stoppen.",
    "Deleting {home} …": "Lösche {home} …",
    "Deleted profile and sandbox data of '{name}'.":
        "Profil und Sandbox-Daten von '{name}' gelöscht.",
    "Profile '{name}' removed (sandbox data kept at {home}).":
        "Profil '{name}' entfernt (Sandbox-Daten bleiben unter {home}).",
    "Error: {msg}": "Fehler: {msg}",
    "A Steam login is already running.": "Es läuft bereits ein Steam-Login.",
    "Stop the running streaming session first; Steam can only run once.":
        "Erst die laufende Streaming-Session stoppen; Steam kann nur einmal "
        "laufen.",
    "Steam login": "Steam-Login",
    "Steam will now start visibly with the isolated sandbox\n{home}\nAny "
    "running desktop Steam will be closed.\n\nLog in there (confirm Steam "
    "Guard), then close Steam.\nContinue?":
        "Steam wird jetzt sichtbar mit der isolierten Sandbox\n{home}\n"
        "gestartet. Ein evtl. laufendes Desktop-Steam wird geschlossen.\n\n"
        "Dort einloggen (Steam Guard bestätigen), dann Steam schließen.\n"
        "Fortfahren?",
    "Steam will now start visibly with the isolated sandbox\n{home}\n\nLog in "
    "there (confirm Steam Guard), then close Steam.\nContinue?":
        "Steam wird jetzt sichtbar mit der isolierten Sandbox\n{home}\n\n"
        "gestartet. Dort einloggen (Steam Guard bestätigen), dann Steam "
        "schließen.\nFortfahren?",
    "Closing desktop Steam …": "Schließe Desktop-Steam …",
    "Preparing sandbox …": "Bereite Sandbox vor …",
    "Preparation failed: {msg}": "Vorbereitung fehlgeschlagen: {msg}",
    "Steam is running isolated for '{name}'. Log in, then close Steam "
    "(Steam → Exit).":
        "Steam läuft isoliert für '{name}'. Einloggen und danach Steam "
        "schließen (Steam → Beenden).",
    "Steam could not be started. Is it installed?":
        "Steam konnte nicht gestartet werden. Ist es installiert?",
    "Profile vanished; nothing was provisioned.":
        "Profil verschwunden; nichts provisioniert.",
    "Steam exited but no login was found. Try 'Start Steam login' again.":
        "Steam wurde beendet, aber kein Login gefunden. »Steam-Login starten« "
        "erneut versuchen.",
    "Login detected, provisioning the game library …":
        "Login erkannt, provisioniere Spiele-Bibliothek …",
    "'{name}' is set up. Start the session on the 'Session' page.":
        "'{name}' ist eingerichtet. Die Session lässt sich auf der Seite "
        "»Session« starten.",
    "Provisioning failed: {msg}": "Provisionierung fehlgeschlagen: {msg}",

    # -- setup page ------------------------------------------------------
    "Preflight checks": "Preflight-Checks",
    "Re-check": "Neu prüfen",
    "checking …": "prüfe …",
    "Check failed: {msg}": "Prüfung fehlgeschlagen: {msg}",
    "{fails} blocker(s), {warns} warning(s). Fix top to bottom.":
        "{fails} Blocker, {warns} Warnung(en). Von oben nach unten beheben.",
    "Ready, {warns} warning(s).": "Bereit, {warns} Warnung(en).",
    "All set ✓": "Alles eingerichtet ✓",
    "Sandbox location": "Sandbox-Speicherort",
    "Where the sandboxes are stored. Changing this moves the existing "
    "sandboxes.":
        "Wo die Sandboxes gespeichert werden. Eine Änderung verschiebt die "
        "bestehenden Sandboxes.",
    "Change …": "Ändern …",
    "Choose a folder for the sandbox homes":
        "Ordner für die Sandbox-Homes wählen",
    "Stop the running session before moving sandboxes.":
        "Stoppe die laufende Session, bevor du Sandboxes verschiebst.",
    "Sandbox location unchanged.": "Sandbox-Speicherort unverändert.",
    "Sandboxes moved to {path}.": "Sandboxes nach {path} verschoben.",
    "Desktop integration": "Desktop-Integration",
    "Start the server GUI at login (autostart)":
        "Server-GUI beim Login starten (Autostart)",
    "Show in the distribution's application menu":
        "Im Anwendungsmenü der Distribution anzeigen",
    "Streaming": "Streaming",
    "Close the desktop Steam when a session starts":
        "Desktop-Steam beim Start einer Session schließen",
    "Off doesn't close the desktop Steam when a session starts.":
        "Aus schließt das Desktop-Steam beim Start einer Session nicht.",
    "Language": "Sprache",
    "Automatic (system)": "Automatisch (System)",
    "Applies after restarting the GUI.": "Wirkt nach einem Neustart der GUI.",
    "Language saved. Restart the GUI to apply.":
        "Sprache gespeichert. GUI neu starten, um sie zu übernehmen.",
    "pkexec is missing, so there is no graphical privilege elevation. Run "
    "fixes manually via sudo (podstage setup).":
        "pkexec fehlt, daher keine grafische Rechtefreigabe. Fixes manuell "
        "per sudo ausführen (podstage setup).",
    "Build image": "Image bauen",
    "Install (pkexec)": "Installieren (pkexec)",
    "Fix (pkexec)": "Beheben (pkexec)",
    "Fix": "Beheben",
    "Autostart enabled. The GUI starts at the next login.":
        "Autostart aktiviert. Die GUI startet beim nächsten Login.",
    "Autostart disabled.": "Autostart deaktiviert.",
    "Added to the application menu.": "Im Anwendungsmenü hinzugefügt.",
    "Removed from the application menu.": "Aus dem Anwendungsmenü entfernt.",
    "Application menu: {e}": "Anwendungsmenü: {e}",
    "{label} running …": "{label} läuft …",
    "Exit code {rc}": "Exit-Code {rc}",
    "Image built.": "Image gebaut.",
    "Keep the last preview frame during static scenes":
        "Bei statischem Bild das letzte Vorschaubild behalten",
    "The capture only delivers frames while the picture changes. Off hides "
    "the preview 45 s after the last new frame.":
        "Die Aufnahme liefert nur Frames, solange sich das Bild ändert. Aus "
        "blendet die Vorschau 45 s nach dem letzten neuen Frame aus.",
    "Experimental features": "Experimentelle Features",
    "Global switches, applied at the next session start. Container-side "
    "features need a current runtime image.":
        "Globale Schalter, gelten ab dem nächsten Session-Start. "
        "Container-seitige Features brauchen ein aktuelles Runtime-Image.",
    "HDR stream": "HDR-Stream",
    "DualSense pad (gyro)": "DualSense-Pad (Gyro)",
    "The session pad becomes a DualSense with real gyro for clients "
    "that send motion data. On a Steam Deck, disable Steam Input for "
    "Moonlight (trade-off: trackpad-as-mouse). Mounts the host /dev "
    "into the session container.":
        "Das Session-Pad wird ein DualSense mit echtem Gyro für Clients, "
        "die Bewegungsdaten senden. Am Steam Deck dafür Steam Input für "
        "Moonlight deaktivieren (Trade-off: Trackpad-als-Maus). Mountet "
        "das Host-/dev in den Session-Container.",
    "gamescope advertises an HDR output and games see DXVK_HDR. Unverified "
    "end to end.":
        "gamescope meldet einen HDR-Output und Spiele sehen DXVK_HDR. "
        "Ende-zu-Ende unverifiziert.",
    "Performance metrics (FPS)": "Performance-Metriken (FPS)",
    "A probe in the container asks gamescope for the presented frametime of "
    "the running game and shows FPS on the Session page. Works on any GPU "
    "vendor; needs a gamescope with the perf query (3.16+).":
        "Eine Sonde im Container fragt gamescope nach der Bildzeit des "
        "laufenden Spiels und zeigt FPS auf der Session-Seite. Läuft mit jedem "
        "GPU-Hersteller; braucht ein gamescope mit Perf-Query (3.16+).",
    "Mouse && keyboard input": "Maus- && Tastatur-Eingabe",
    "Streams the client's mouse and keyboard into the session; games can "
    "lock the pointer for mouse look.":
        "Leitet Maus und Tastatur des Clients in die Session; Spiele können "
        "den Zeiger für Mouse-Look locken.",
    "Recommended off for controller-only clients. Applies at the next "
    "session start.":
        "Für reine Controller-Clients empfohlen: aus. Gilt ab dem nächsten "
        "Session-Start.",
    "Experimental features apply from the next session start.":
        "Experimentelle Features gelten ab dem nächsten Session-Start.",
    "Checks the GitHub releases for a newer version.":
        "Prüft die GitHub-Releases auf eine neuere Version.",
    "Installed: {current}": "Installiert: {current}",
    "Check for updates": "Auf Updates prüfen",
    "Open release page": "Release-Seite öffnen",
    "podstage {current} is up to date.": "podstage {current} ist aktuell.",
    "Version {latest} is available (installed: {current}).":
        "Version {latest} ist verfügbar (installiert: {current}).",
    "The release notes mention an image rebuild.":
        "Die Release-Notes erwähnen einen Image-Rebuild.",
    "Update check failed: {msg}": "Update-Prüfung fehlgeschlagen: {msg}",
    "udev rules installed. Input isolation and device access "
    "are set up.":
        "udev-Regeln installiert. Eingabe-Isolation und Gerätezugriff "
        "sind eingerichtet.",
    "Done.": "Erledigt.",

    # -- setup page: uninstall --------------------------------------------
    "Remove podstage": "podstage entfernen",
    "Removes the udev rules, firewall ports, runtime "
    "image, data and configuration. Shared pieces stay "
    "unless selected.":
        "Entfernt die udev-Regeln, Firewall-Ports, das Runtime-Image, "
        "Daten und Konfiguration. Geteilte Bestandteile bleiben, außer sie "
        "sind ausgewählt.",
    "Also delete sandboxes (Steam logins, saves)":
        "Auch Sandboxen löschen (Steam-Logins, Spielstände)",
    "Also remove shared pieces (mDNS service, NVIDIA CDI spec)":
        "Auch geteilte Bestandteile entfernen (mDNS-Dienst, NVIDIA-CDI-Spec)",
    "Uninstall …": "Deinstallieren …",
    "Nothing to remove.": "Nichts zu entfernen.",
    "Remove podstage?": "podstage entfernen?",
    "This removes:": "Das entfernt:",
    "(shared — kept)": "(geteilt — bleibt)",
    "pkexec is missing — finish with the CLI: "
    "podstage uninstall":
        "pkexec fehlt — mit der CLI abschließen: podstage uninstall",
    "Removed ({done}) — still present: {names}":
        "Entfernt ({done}) — noch vorhanden: {names}",
    "podstage removed — no residues found. ({done})":
        "podstage entfernt — keine Rückstände gefunden. ({done})",

    # -- login guards ------------------------------------------------------
    "Open sandbox Steam": "Sandbox-Steam öffnen",
    "Close sandbox Steam?": "Sandbox-Steam schließen?",
    "The sandbox Steam is open on the desktop. Close it and "
    "start the stream?":
        "Das Sandbox-Steam ist auf dem Desktop geöffnet. Schließen und den "
        "Stream starten?",
    "Could not close the sandbox Steam; close it manually.":
        "Sandbox-Steam konnte nicht geschlossen werden; bitte manuell schließen.",
    "'{name}' has no Steam login yet. Log in via "
    "the 'Sandboxes' page first.":
        "»{name}« hat noch keinen Steam-Login. Zuerst über die Seite "
        "»Sandboxen« anmelden.",
    "Follow the client's resolution":
        "Auflösung folgt dem Client",
    "Render at the first connecting client's resolution, locked until "
    "the session restarts. The profile resolution above is only the "
    "fallback. Off: always render at the profile resolution.":
        "Rendert in der Auflösung des zuerst verbindenden Clients, fixiert "
        "bis zum Neustart der Session. Die Profil-Auflösung oben ist nur der "
        "Fallback. Aus: es wird immer in der Profil-Auflösung gerendert.",
    "Client (auto)":
        "Client (auto)",
    "{w}x{h}@{r} · locked until the session restarts":
        "{w}x{h}@{r} · fixiert bis zum Session-Neustart",
    "waiting for the first client …":
        "warte auf den ersten Client …",
}
