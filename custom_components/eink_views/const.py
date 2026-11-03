"""Constants for E-Ink Views."""

from __future__ import annotations

DOMAIN = "eink_views"

CONF_ACCESS_KEY = "access_key"
CONF_HEIGHT = "height"
CONF_ROTATE_KEY = "rotate_key"
CONF_VIEWS_DIR = "views_dir"
CONF_WIDTH = "width"

DEFAULT_HEIGHT = 480
DEFAULT_VIEWS_DIR = "eink_views/display"
# A views directory is "name" or "parent/name". In the second form, parent/_macros.svg.j2
# is shared by every display below parent.
VIEWS_DIR_PATTERN = r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)?$"
DEFAULT_WIDTH = 800

MACROS_FILE = "_macros.svg.j2"
VIEWS_FILE = "views.yaml"
