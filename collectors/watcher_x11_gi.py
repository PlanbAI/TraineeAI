#!/usr/bin/env python3

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi


def dump_accessible(node, level=0, max_depth=8):
    indent = "  " * level

    try:
        role = node.get_role_name()
        name = node.get_name()
    except Exception:
        return

    print(f"{indent}{role!r}: {name!r}")

    if level >= max_depth:
        return

    try:
        count = node.get_child_count()
    except Exception:
        return

    for i in range(count):
        try:
            child = node.get_child_at_index(i)
            if child:
                dump_accessible(child, level + 1, max_depth)
        except Exception:
            pass


def main():
    desktop = Atspi.get_desktop(0)

    print("Applications:\n")

    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)

        if app is None:
            continue

        try:
            name = app.get_name()
            role = app.get_role_name()
        except Exception:
            continue

        print(f"{i}: {role!r} -> {name!r}")

    print("\nSelect application number:")

    index = int(input("> "))

    app = desktop.get_child_at_index(index)

    if app is None:
        print("Application not found")
        return

    print(f"\nAccessibility tree for: {app.get_name()}\n")

    dump_accessible(app)


if __name__ == "__main__":
    main()
