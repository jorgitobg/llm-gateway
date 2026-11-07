from __future__ import annotations

from pathlib import Path

import llm_gateway


def test_package_ships_the_py_typed_marker() -> None:
    # Without it, dependants running a strict type checker get no type information.
    assert (Path(llm_gateway.__file__).parent / "py.typed").is_file()
