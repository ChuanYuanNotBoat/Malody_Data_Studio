"""Load legacy package imports independently of the checkout directory name."""

import importlib.util
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "malody_api" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "malody_api",
        PROJECT_ROOT / "__init__.py",
        submodule_search_locations=[str(PROJECT_ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["malody_api"] = package
    spec.loader.exec_module(package)
