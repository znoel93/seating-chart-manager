"""
main.py — Entry point for the Seating Chart Manager.
"""

from ui import SeatingApp

if __name__ == "__main__":
    app = SeatingApp()

    # On macOS, Python apps launched from PyCharm or Terminal don't
    # automatically become the foreground app. Force it.
    app.lift()
    app.attributes("-topmost", True)
    app.after(100, lambda: app.attributes("-topmost", False))
    app.focus_force()

    app.mainloop()