"""Comfy-gmx — a node-based workbench for GROMACS / Martini molecular dynamics.

Everything the server needs is in the Python standard library, so the package
runs under any CPython >= 3.9 without a pip install.  Optional extras (RDKit,
MDAnalysis, ...) are only ever invoked as external tools inside their own conda
environments, never imported here.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
