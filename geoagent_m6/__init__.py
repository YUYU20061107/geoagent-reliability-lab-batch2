"""GeoAgent M6 public core.

Pure-standard-library, offline-only engineering upgrades for GIS semantic
reliability, executor evidence chains, provenance and release verification.
No network client, no credentials, no provider calls are part of this package.
"""

from .outcomes import Outcome, Responsibility, Verdict, verdict

__all__ = ["Outcome", "Responsibility", "Verdict", "verdict", "__version__"]
__version__ = "6.0.0-m6-public-core"
