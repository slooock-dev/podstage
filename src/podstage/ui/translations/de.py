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
    "Pair a new moonlight client by PIN (session must be running)":
        "Neuen moonlight-Client per PIN pairen (Session muss laufen)",
    "Game": "Spiel",
    "Preview": "Vorschau",
    "Refresh every": "Aktualisieren alle",
    "How often the preview is captured, 0 turns it off. From the next "
    "stream start.":
        "Wie oft die Vorschau aufgenommen wird, 0 schaltet sie aus. Ab dem "
        "nächsten Stream-Start.",
    "{w}x{h}@{r} | follows the connected client":
        "{w}x{h}@{r} | folgt dem verbundenen Client",
    "Preview appears here while streaming.":
        "Die Vorschau erscheint hier während des Streams.",
    "Preview is off": "Vorschau ist aus",
    "waiting for preview …": "warte auf Vorschau …",
    "no new frames": "keine neuen Frames",
    "Stream quality": "Stream-Qualität",
    "NVENC preset": "NVENC-Preset",
    "Apply live": "Live übernehmen",
    "Apply immediately to the running session (stream briefly reconnects)":
        "Auf die laufende Session sofort anwenden (Stream verbindet kurz neu)",
    "Bitrate & codec come from the moonlight client. These are the "
    "server-side quality.":
        "Bitrate & Codec kommen vom moonlight-Client. Dies ist die "
        "serverseitige Qualität.",
    "Bitrate & codec come from the moonlight client. {backend} applies "
    "this at the next session start.":
        "Bitrate & Codec kommen vom moonlight-Client. {backend} übernimmt "
        "dies ab dem nächsten Session-Start.",
    "Error correction": "Fehlerkorrektur",
    "moonshine default ({pct} %)": "moonshine-Standard ({pct} %)",
    "Redundancy against packet loss. Higher survives a lossy WiFi and "
    "costs bandwidth. 0 turns it off.":
        "Redundanz gegen Paketverlust. Höher übersteht ein verlustbehaftetes "
        "WLAN und kostet Bandbreite. 0 schaltet sie ab.",
    "Saved. Applies at the next session start.":
        "Gespeichert. Gilt ab dem nächsten Session-Start.",
    "The {backend} backend has no live quality settings. These apply to "
    "sunshine profiles only.":
        "Das Backend {backend} hat keine Qualitätseinstellungen zur Laufzeit. "
        "Diese gelten nur für sunshine-Profile.",
    "VBV buffer increase (%): larger reduces artifacts in fast motion. "
    "0 = sunshine default.":
        "VBV-Puffer-Erhöhung (%): größer reduziert Artefakte bei schnellen "
        "Bewegungen. 0 = sunshine-Standard.",
    "Open sunshine web UI": "sunshine Web-UI öffnen",
    "Saved. Applies from the next stream start. Use 'Apply live' for a "
    "running session.":
        "Gespeichert. Gilt ab dem nächsten Stream-Start. »Live übernehmen« "
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
    "PIN submitted but no pairing completed. Restart the "
    "pairing in moonlight.":
        "PIN übermittelt, aber kein Pairing abgeschlossen. Pairing in "
        "moonlight neu starten.",
    "Client '{name}' paired. moonlight can stream now.":
        "Client '{name}' gepairt. moonlight kann jetzt streamen.",
    "Paired. moonlight can stream now.":
        "Gepairt. moonlight kann jetzt streamen.",
    "Pairing failed: {msg}": "Pairing fehlgeschlagen: {msg}",
    "Applying live … (stream briefly interrupts)":
        "Wende live an … (Stream unterbricht kurz)",
    "Applied live. The stream is reconnecting.":
        "Live angewendet. Der Stream verbindet sich neu.",
    "No running session. The setting is saved and applies from the next start.":
        "Keine laufende Session. Die Einstellung ist gespeichert und gilt ab "
        "dem nächsten Start.",
    "Saved. Live apply failed: {msg}":
        "Gespeichert. Live-Anwendung fehlgeschlagen: {msg}",

    # -- pair dialog -----------------------------------------------------
    "Pair client": "Client pairen",
    "PIN from moonlight, e.g. 1234": "PIN aus moonlight, z. B. 1234",
    "Device name": "Gerätename",
    "Select '{server}' in moonlight and enter the 4-digit PIN it shows here.":
        "In moonlight »{server}« auswählen und die angezeigte 4-stellige "
        "PIN hier eintragen.",

    # -- sunshine web UI dialog ------------------------------------------
    "sunshine web UI": "sunshine Web-UI",
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
    "VAAPI rate-control mode. Not every mode works on every GPU.":
        "VAAPI-Ratensteuerung. Nicht jeder Modus läuft auf jeder GPU.",
    "Fewer dropped frames on scene changes, at the cost of quality "
    "during motion.":
        "Weniger verworfene Frames bei Szenenwechseln, dafür Qualitätsverlust "
        "bei Bewegung.",

    # -- sandbox page: table + buttons ----------------------------------
    "Steam sandboxes": "Steam-Sandboxen",
    "Resolution": "Auflösung",
    "Size": "Größe",
    "New …": "Neu …",
    "Edit …": "Bearbeiten …",
    "Delete …": "Löschen …",
    "Start Steam login": "Steam-Login starten",
    "Clear overlay …": "Overlay leeren …",
    "Discards this sandbox's writes onto the shared game libraries. Host "
    "libraries and the sandbox HOME are untouched.":
        "Verwirft die Schreibzugriffe dieser Sandbox auf die geteilten "
        "Spiele-Bibliotheken. Host-Bibliotheken und Sandbox-HOME bleiben "
        "unberührt.",
    "Clear overlay?": "Overlay leeren?",
    "Discard '{name}'s writes onto the shared game libraries ({size})? Game "
    "updates applied in a session are lost and re-apply next time. The host "
    "libraries and the sandbox HOME are untouched.":
        "Die Schreibzugriffe von '{name}' auf die geteilten "
        "Spiele-Bibliotheken verwerfen ({size})? In einer Session angewendete "
        "Spiel-Updates gehen verloren und werden beim nächsten Mal neu "
        "angewendet. Host-Bibliotheken und Sandbox-HOME bleiben unberührt.",
    "Overlay of '{name}' cleared.": "Overlay von '{name}' geleert.",
    "Pick at startup": "Beim Start wählen",
    "✓ logged in": "✓ eingeloggt",
    "empty": "leer",
    "✗ no login": "✗ kein Login",
    "'Streamed login' signs in over the stream, 'Start Steam login' opens "
    "the isolated Steam on the desktop. Either way the game library "
    "is provisioned afterwards.":
        "»Gestreamter Login« meldet über den Stream an, »Steam-Login "
        "starten« öffnet das isolierte Steam auf dem Desktop. In beiden "
        "Fällen wird die Spiele-Bibliothek danach provisioniert.",
    "Streamed login": "Gestreamter Login",
    "Extra mounts": "Zusätzliche Mounts",
    "Invalid extra mount": "Ungültiger Mount",
    "One host directory per line, mounted at the same path in the "
    "session. Read-only overlay by default. Append ':rw' for "
    "launchers that update themselves in place.":
        "Ein Host-Verzeichnis pro Zeile, wird unter demselben Pfad in die "
        "Session gemountet. Standard ist ein read-only-Overlay. ':rw' "
        "anhängen für Launcher, die sich selbst aktualisieren.",
    "Boots this sandbox into Big Picture's Steam sign-in over the "
    "stream. No window opens on the host.":
        "Startet diese Sandbox in Steams Big-Picture-Anmeldung über den "
        "Stream. Auf dem Host öffnet sich kein Fenster.",
    "The sandbox\n{home}\nboots into Big Picture's Steam sign-in over "
    "the stream: connect with moonlight and log in with the QR code "
    "(Steam Mobile App) or the on-screen keyboard.\n\nContinue?":
        "Die Sandbox\n{home}\nstartet in Steams Big-Picture-Anmeldung über "
        "den Stream: mit moonlight verbinden und per QR-Code (Steam-Mobile-"
        "App) oder Bildschirmtastatur einloggen.\n\nFortfahren?",
    "Starting login session …": "Starte Login-Session …",
    "Login session failed: {msg}": "Login-Session fehlgeschlagen: {msg}",
    "Login session running: connect with moonlight and sign in. "
    "Stop the session on the Session page when you are done. The "
    "next regular start provisions the game library.":
        "Login-Session läuft: mit moonlight verbinden und einloggen. "
        "Danach die Session auf der Session-Seite stoppen. Der nächste "
        "normale Start provisioniert die Spiele-Bibliothek.",

    # -- sandbox page: profile dialog -----------------------------------
    "Edit profile": "Profil bearbeiten",
    "New profile": "Neues Profil",
    "custom": "benutzerdefiniert",
    "e.g. deck, laptop, livingroom": "z. B. deck, laptop, wohnzimmer",
    "WidthxHeight@Hz, e.g. 1920x1080@60": "BreitexHöhe@Hz, z. B. 1920x1080@60",
    "moonlight port": "moonlight-Port",
    "Backend": "Backend",
    "sunshine works on every supported GPU. moonshine encodes with Vulkan "
    "Video, which needs an NVIDIA RTX, AMD RDNA2+ or Intel Arc GPU. "
    "The Setup page checks this machine.":
        "sunshine läuft auf jeder unterstützten GPU. moonshine kodiert per "
        "Vulkan Video, was eine NVIDIA RTX, AMD RDNA2+ oder Intel Arc "
        "voraussetzt. Die Setup-Seite prüft diese Maschine.",
    "Needs Vulkan video encode (NVIDIA RTX, AMD RDNA2+, Intel Arc). Save "
    "the profile, then build its image on the Setup page.":
        "Braucht Vulkan-Video-Encode (NVIDIA RTX, AMD RDNA2+, Intel Arc). "
        "Profil speichern, dann auf der Setup-Seite das Image bauen.",
    "Keyboard": "Tastatur",
    "variant, e.g. nodeadkeys": "Variante, z. B. nodeadkeys",
    "XKB layout of the streamed session. Empty keeps moonshine's default "
    "(us).":
        "XKB-Belegung der gestreamten Session. Leer behält moonshines "
        "Standard (us).",
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
    "Stop the running streaming session first. Steam can only run once.":
        "Erst die laufende Streaming-Session stoppen. Steam kann nur einmal "
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
    "Profile vanished. Nothing was provisioned.":
        "Profil verschwunden. Nichts provisioniert.",
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
    # "Host" and "Streaming" are identical in German, so the English fallback
    # already covers those two check-group headings.
    "{name} backend": "Backend {name}",
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
    "Off: disable the desktop Steam's \"Guide Button "
    "Focuses Steam\", or Guide presses open its Big Picture.":
        "Aus: im Desktop-Steam \"Guide Button Focuses Steam\" "
        "deaktivieren, sonst öffnen Guide-Drücke dessen Big Picture.",
    "Language": "Sprache",
    "Automatic (system)": "Automatisch (System)",
    "Applies after restarting the GUI.": "Wirkt nach einem Neustart der GUI.",
    "Language saved. Restart the GUI to apply.":
        "Sprache gespeichert. GUI neu starten, um sie zu übernehmen.",
    "pkexec is missing: no graphical privilege "
    "elevation. Run fixes via sudo (podstage setup).":
        "pkexec fehlt: keine grafische Rechtefreigabe. Fixes per sudo "
        "ausführen (podstage setup).",
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
    "Building {image} | step {n}/{total} | {what}":
        "Baue {image} | Schritt {n}/{total} | {what}",
    "Clean up": "Aufräumen",
    "No superseded images.": "Keine überholten Images.",
    "Removed {n} superseded image(s), {gb} GB.":
        "{n} überholte(s) Image(s) entfernt, {gb} GB.",
    "Keep the last preview frame during static scenes":
        "Bei statischem Bild das letzte Vorschaubild behalten",
    "Off hides the preview 45 s after the last new frame.":
        "Aus blendet die Vorschau 45 s nach dem letzten neuen Frame aus.",
    "Experimental features": "Experimentelle Features",
    "Applied at the next session start. Container-side features need a "
    "current runtime image.":
        "Gilt ab dem nächsten Session-Start. Container-seitige Features "
        "brauchen ein aktuelles Runtime-Image.",
    "HDR stream": "HDR-Stream",
    "DualSense pad (gyro)": "DualSense-Pad (Gyro)",
    "sunshine only. For PlayStation controllers.":
        "Nur sunshine. Für PlayStation-Controller.",
    "Emulates a DualSense instead of the Xbox pad: gyro, matching glyphs. "
    "Needs /dev/uhid. Steam Deck: turn Steam Input off in moonlight.":
        "Emuliert ein DualSense statt des Xbox-Pads: Gyro, passende "
        "Tastensymbole. Braucht /dev/uhid. Steam Deck: Steam Input in "
        "moonlight ausschalten.",
    "Enables HDR in the compositor. Whether the stream carries it is "
    "unverified.":
        "Schaltet HDR im Compositor ein. Ob der Stream es trägt, ist "
        "unverifiziert.",
    "Performance metrics (FPS)": "Performance-Metriken (FPS)",
    "Shows the running game's FPS on the Session page. Needs a gamescope "
    "with the perf query (3.16+).":
        "Zeigt die FPS des laufenden Spiels auf der Session-Seite. Braucht "
        "ein gamescope mit Perf-Query (3.16+).",
    "Hold Select to press Guide": "Select halten drückt Guide",
    "Hold Select/Back to send Guide, which opens the Steam menu. For "
    "clients that cannot send it themselves. A Steam Deck's local "
    "Steam consumes the button.":
        "Select/Back halten sendet Guide, das öffnet das Steam-Menü. Für "
        "Clients, die es selbst nicht senden können. Am Steam Deck "
        "konsumiert das lokale Steam die Taste.",
    "Applies at the next session start.":
        "Gilt ab dem nächsten Session-Start.",
    "Reconnect gamepad": "Gamepad neu verbinden",
    "Write game updates to the host library":
        "Spiel-Updates in die Host-Library schreiben",
    "Mounts the shared Steam libraries read/write. Updates from the "
    "sandbox persist on the host.":
        "Bindet die geteilten Steam-Libraries read/write ein. Updates aus "
        "der Sandbox bleiben auf dem Host erhalten.",
    "Host library": "Host-Library",
    "Briefly disconnects and reconnects the streamed pads.":
        "Trennt die gestreamten Pads kurz und verbindet sie neu.",
    "Gamepads disconnected and reconnected.":
        "Gamepads getrennt und neu verbunden.",
    "reconnecting …": "verbinde neu …",
    "Gamepad reconnect": "Gamepad-Reconnect",
    "Lets the reconnect button fake an unplug/replug of the streamed pads. "
    "No effect on DualSense or moonshine pads.":
        "Lässt den Reconnect-Knopf ein Ab- und Anstecken der gestreamten "
        "Pads vortäuschen. Ohne Wirkung auf DualSense- und moonshine-Pads.",
    "Mouse && keyboard input": "Maus- && Tastatur-Eingabe",
    "Streams the client's mouse and keyboard into the session.":
        "Leitet Maus und Tastatur des Clients in die Session.",
    "Recommended off for controller-only clients. Applies at the next "
    "session start.":
        "Für reine Controller-Clients empfohlen: aus. Gilt ab dem nächsten "
        "Session-Start.",
    "sunshine only.": "Nur sunshine.",
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
    "image, data and configuration.":
        "Entfernt die udev-Regeln, Firewall-Ports, das Runtime-Image, "
        "Daten und Konfiguration.",
    "Also delete sandboxes (Steam logins, saves)":
        "Auch Sandboxen löschen (Steam-Logins, Spielstände)",
    "Also remove shared pieces (mDNS service, NVIDIA CDI spec)":
        "Auch geteilte Bestandteile entfernen (mDNS-Dienst, NVIDIA-CDI-Spec)",
    "Uninstall …": "Deinstallieren …",
    "Nothing to remove.": "Nichts zu entfernen.",
    "Remove podstage?": "podstage entfernen?",
    "This removes:": "Das entfernt:",
    "(shared, kept)": "(geteilt, bleibt)",
    "pkexec is missing. Finish with the CLI: "
    "podstage uninstall":
        "pkexec fehlt. Mit der CLI abschließen: podstage uninstall",
    "Removed ({done}). Still present: {names}":
        "Entfernt ({done}). Noch vorhanden: {names}",
    "podstage removed, no residues found. ({done})":
        "podstage entfernt, keine Rückstände gefunden. ({done})",

    # -- login guards ------------------------------------------------------
    "Open sandbox Steam": "Sandbox-Steam öffnen",
    "Close sandbox Steam?": "Sandbox-Steam schließen?",
    "The sandbox Steam is open on the desktop. Close it and "
    "start the stream?":
        "Das Sandbox-Steam ist auf dem Desktop geöffnet. Schließen und den "
        "Stream starten?",
    "Could not close the sandbox Steam. Close it manually.":
        "Sandbox-Steam konnte nicht geschlossen werden. Bitte manuell schließen.",
    "'{name}' has no Steam login yet. Log in via "
    "the 'Sandboxes' page first.":
        "»{name}« hat noch keinen Steam-Login. Zuerst über die Seite "
        "»Sandboxen« anmelden.",
    "Follow the client's resolution":
        "Auflösung folgt dem Client",
    "Render at the connecting client's resolution. The one above is only "
    "the fallback. sunshine locks the first client's mode until the "
    "session restarts, moonshine follows every reconnect.":
        "Rendert in der Auflösung des verbindenden Clients. Die oben ist nur "
        "der Fallback. sunshine fixiert den Modus des ersten Clients bis zum "
        "Session-Neustart, moonshine folgt jedem Reconnect.",
    "Stop the session to switch the backend.":
        "Zum Wechseln des Backends die Session stoppen.",
    "Applies at the next session start. Each backend keeps "
    "its own pairings.":
        "Gilt ab dem nächsten Session-Start. Jedes Backend führt eigene "
        "Pairings.",
    "Client (auto)":
        "Client (auto)",
    "Add folder …": "Ordner hinzufügen …",
    "writable": "schreibbar",
    "Add the chosen folder as ':rw', which lets the session change host "
    "files.":
        "Fügt den gewählten Ordner als »:rw« hinzu, die Session darf dann "
        "Host-Dateien verändern.",
    "Choose a folder to mount into the session":
        "Ordner wählen, der in die Session gemountet wird",
    "{w}x{h}@{r} | locked until the session restarts":
        "{w}x{h}@{r} | fixiert bis zum Session-Neustart",
    "waiting for the first client …":
        "warte auf den ersten Client …",
}
