"""Launch recon-plus dashboard."""
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "recon_plus"] + sys.argv[1:],
)
