"""Software versions recorded in provenance and the health endpoint."""

from __future__ import annotations

import platform
import sys

import astropy
import fastapi
import numpy
import pydantic
import scipy

from skyshift import __version__
from skyshift.contracts import SoftwareVersion


def software_versions() -> list[SoftwareVersion]:
    return [
        SoftwareVersion(name="skyshift", version=__version__),
        SoftwareVersion(name="python", version=sys.version.split()[0]),
        SoftwareVersion(name="numpy", version=numpy.__version__),
        SoftwareVersion(name="scipy", version=scipy.__version__),
        SoftwareVersion(name="astropy", version=astropy.__version__),
        SoftwareVersion(name="pydantic", version=pydantic.__version__),
        SoftwareVersion(name="fastapi", version=fastapi.__version__),
        SoftwareVersion(name="platform", version=platform.platform()),
    ]
