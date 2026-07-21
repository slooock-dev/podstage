"""podstage core library.

Modules:
  steam        – locate the desktop Steam install and its library folders
  provisioner  – build an isolated streaming Steam HOME with shared game files
  runtime      – build + manage the rootless podman runtime container
  udev         – host udev rules (seat isolation + per-user device access)
  session      – client profile ↔ runtime container lifecycle
  doctor       – environment validation for all of the above
"""
