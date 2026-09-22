"""Where forefst.py lives, for whichever layout the tests are run from.

In this repo the suite sits at <repo>/analysis/tests/, so the tools are two directories up, and
every test computed that path for itself. The AUDITOR PACKAGE flattens the layout to
<bundle>/tests/ with the tools in <bundle>/tools/ -- so each of those computations resolved to
<bundle>/../forefst.py, which does not exist, and the RC1 check reported 60 spurious CLI errors
against a tool that was sitting in the package the whole time.

The fix is to LOOK for the file rather than assume one layout. FOREFST_REPO overrides, for a
caller who wants a specific tree. When nothing is found the repo-layout path is returned
unchanged, so a genuinely missing tool still fails the way it always did.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_LAYOUT = os.path.dirname(os.path.dirname(HERE))        # <repo>/analysis/tests -> <repo>
_CANDIDATES = (
    _REPO_LAYOUT,
    os.path.join(os.path.dirname(HERE), "tools"),            # <bundle>/tests -> <bundle>/tools
    os.path.dirname(HERE),                                   # tools beside the suite
)


def _pick():
    env = os.environ.get("FOREFST_REPO")
    for d in ((env,) if env else ()) + _CANDIDATES:
        if d and os.path.isfile(os.path.join(d, "forefst.py")):
            return d
    return _REPO_LAYOUT


REPO = _pick()
