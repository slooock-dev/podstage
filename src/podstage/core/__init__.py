"""podstage core library.

Modules:
  backends      the streaming backends and what each one implies host side
  steam         locate the desktop Steam install and its library folders
  provisioner   build an isolated streaming Steam HOME with shared game files
  runtime       build + manage the rootless podman runtime container
  sandbox       size, remove and rename a profile's HOME and overlay dirs
  udev          host udev rules (seat isolation + per-user device access)
  session       client profile to runtime container lifecycle
  monitor       one status snapshot per GUI refresh (GPU, host load, FPS)
  sunshine_api  Sunshine's config/pairing HTTPS API
  moonshine_api moonshine's pairing HTTP API
  desktop       .desktop entry and icon for the host menu
  elevate       the one root step, run through pkexec
  update        on-demand check for a newer release
  doctor        environment validation for all of the above
  teardown      detection-based uninstall of everything setup created
"""
