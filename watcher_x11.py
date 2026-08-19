import time
from datetime import datetime

from Xlib import X, display
from Xlib.ext import xprop


def get_active_window(root):
    atom = root.display.intern_atom("_NET_ACTIVE_WINDOW")
    prop = root.get_full_property(atom, X.AnyPropertyType)

    if not prop or not prop.value:
        return None

    return prop.value[0]


def get_window_title(window):
    try:
        prop = window.get_full_property(
            window.display.intern_atom("_NET_WM_NAME"),
            X.AnyPropertyType,
        )

        if prop and prop.value:
            return prop.value.decode("utf-8", errors="replace")
    except Exception:
        pass

    return ""


def get_pid(window):
    try:
        atom = window.display.intern_atom("_NET_WM_PID")
        prop = window.get_full_property(atom, X.AnyPropertyType)

        if prop and prop.value:
            return prop.value[0]
    except Exception:
        pass

    return None


def main():
    display_connection = display.Display()
    root = display_connection.screen().root

    previous_window = None

    print("Linux Collector started")
    print("Waiting for window changes...\n")

    while True:
        try:
            window_id = get_active_window(root)

            if window_id and window_id != previous_window:
                window = display_connection.create_resource_object(
                    "window",
                    window_id,
                )

                title = get_window_title(window)
                pid = get_pid(window)

                timestamp = datetime.now().isoformat(timespec="seconds")

                print(
                    f"{timestamp} | "
                    f"window={window_id} | "
                    f"pid={pid} | "
                    f"title={title!r}"
                )

                previous_window = window_id

            time.sleep(0.2)

        except KeyboardInterrupt:
            print("\nCollector stopped.")
            break


if __name__ == "__main__":
    main()