"""German (de) translation catalog. Keys are the English source strings.

Only entries that actually differ from the English source are listed; where a
term is identical in both languages (Session, Setup, Start, Stop, Client, Port,
Login, Pause, Backend …) the English fallback already yields correct German.
Referenced page/button names use »…« guillemets, matching the code style.
"""

from __future__ import annotations

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
    "Preview is off": "Vorschau ist aus",
    "waiting for preview …": "warte auf Vorschau …",
    "Load": "Auslastung",
    "Stream quality": "Stream-Qualität",
    "NVENC preset": "NVENC-Preset",
    "Apply live": "Live übernehmen",
    "Apply immediately to the running session (stream briefly reconnects)":
        "Auf die laufende Session sofort anwenden (Stream verbindet kurz neu)",
    "Bitrate & codec are chosen by the Moonlight client; these control encoder "
    "quality on the server side.":
        "Bitrate & Codec wählt der Moonlight-Client; diese steuern die "
        "Encoder-Qualität serverseitig.",
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
    "Sunshine rejected the PIN. Reconnect in Moonlight and enter the new PIN.":
        "Sunshine hat die PIN abgelehnt. In Moonlight neu verbinden und die "
        "neue PIN eintragen.",
    "Client '{name}' paired. Moonlight can stream now.":
        "Client '{name}' gepairt. Moonlight kann jetzt streamen.",
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

    # -- VAAPI quality (AMD) --------------------------------------------
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
    "VAAPI quality profile: the AMD encoder's speed/quality tradeoff.":
        "VAAPI-Qualitätsprofil: Abwägung zwischen Geschwindigkeit und Qualität "
        "des AMD-Encoders.",
    "VAAPI rate-control mode. 'auto' lets the driver choose; not every "
    "mode is supported on every GPU.":
        "VAAPI-Ratensteuerung. »auto« überlässt die Wahl dem Treiber; nicht "
        "jeder Modus wird von jeder GPU unterstützt.",
    "Avoids dropped frames over the network during scene changes, but "
    "quality may drop during motion.":
        "Vermeidet verworfene Frames über das Netzwerk bei Szenenwechseln, "
        "die Qualität kann bei Bewegung aber sinken.",

    # -- sandbox page: table + buttons ----------------------------------
    "Client sandboxes": "Client-Sandboxen",
    "Resolution": "Auflösung",
    "Size": "Größe",
    "New …": "Neu …",
    "Edit …": "Bearbeiten …",
    "Delete …": "Löschen …",
    "Start Steam login": "Steam-Login starten",
    "Pick at startup": "Beim Start wählen",
    "✓ logged in": "✓ eingeloggt",
    "— empty": "— leer",
    "✗ no login": "✗ kein Login",
    "Setup: 'Start Steam login' opens the isolated Steam visibly on the "
    "desktop. Log in there (Steam Guard), then close Steam; the game library "
    "is provisioned automatically.":
        "Einrichtung: »Steam-Login starten« öffnet das isolierte Steam sichtbar "
        "auf dem Desktop. Dort einloggen (Steam Guard), dann Steam schließen; "
        "die Spiele-Bibliothek wird automatisch provisioniert.",

    # -- sandbox page: profile dialog -----------------------------------
    "Edit profile": "Profil bearbeiten",
    "New profile": "Neues Profil",
    "custom": "benutzerdefiniert",
    "e.g. deck, laptop, livingroom": "z. B. deck, laptop, wohnzimmer",
    "WidthxHeight@Hz, e.g. 1920x1080@60": "BreitexHöhe@Hz, z. B. 1920x1080@60",
    "Sunshine port": "Sunshine-Port",
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
    "Only letters, digits, '-' and '_' are allowed.":
        "Nur Buchstaben, Ziffern, '-' und '_' erlaubt.",
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
    "udev rules installed. Input isolation and device access "
    "are set up.":
        "udev-Regeln installiert. Eingabe-Isolation und Gerätezugriff "
        "sind eingerichtet.",
    "Done.": "Erledigt.",
    "podman build failed:\n{tail}": "podman build fehlgeschlagen:\n{tail}",
}
