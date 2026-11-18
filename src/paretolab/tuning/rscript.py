"""Finding R's ``Rscript`` (it is often not on the PATH on Windows) and installed R packages."""
import glob
import os
import shutil
import subprocess
from pathlib import Path

from paretolab.execution.process import WINDOWS

ENV_VAR = "PARETOLAB_RSCRIPT"
INSTALL_R = "Install R from https://cran.r-project.org (or set PARETOLAB_RSCRIPT to the Rscript program)."
INSTALL_IRACE = 'In R, run: install.packages("irace")'
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def find_rscript() -> str | None:
    """$PARETOLAB_RSCRIPT, then the PATH, then the usual install folders (newest version first)."""
    given = os.environ.get(ENV_VAR)
    if given:
        return given if Path(given).is_file() else shutil.which(given)
    found = shutil.which("Rscript")
    if found:
        return found
    patterns = []
    if WINDOWS:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", ""),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base:
                patterns.append(os.path.join(base, "R", "R-*", "bin", "Rscript.exe"))
    else:
        patterns += ["/opt/R/*/bin/Rscript", "/usr/local/bin/Rscript",
                     "/Library/Frameworks/R.framework/Resources/bin/Rscript"]
    candidates = sorted({c for p in patterns for c in glob.glob(p)}, key=_version_key)
    return candidates[-1] if candidates else None


def _version_key(path: str):
    parts = []
    for piece in Path(path).parts:
        if piece.startswith("R-"):
            parts = [int(x) if x.isdigit() else 0 for x in piece[2:].split(".")]
    return parts, path


def package_version(rscript: str, package: str) -> str | None:
    """Installed version of an R package, or None."""
    try:
        r = subprocess.run([rscript, "-e", f"cat(as.character(packageVersion('{package}')))"],
                           capture_output=True, text=True, timeout=120, **_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    version = r.stdout.strip()
    return version if r.returncode == 0 and version else None
