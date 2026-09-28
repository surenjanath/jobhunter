"""JobHunter scanner package. Importing it makes sure the local (git-ignored) config files exist."""
from src import localfiles as _localfiles

_localfiles.ensure()
