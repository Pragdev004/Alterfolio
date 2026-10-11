import importlib
import sys


def test_backend_packages_import_and_python_is_supported():
    assert sys.version_info >= (3, 11)
    for name in ("app", "app.domain", "app.quant"):
        importlib.import_module(name)
