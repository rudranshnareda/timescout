"""
Claude Usage Widget
===================

A small always-on-top desktop widget that shows your live Claude Code usage:
the 5-hour session window, the weekly (all-models) window, and per-model
weekly windows when your plan exposes them.

It reads the OAuth token Claude Code already stores on this machine
(~/.claude/.credentials.json) and polls Anthropic's usage endpoint. No token
is ever stored, logged, or transmitted anywhere except to api.anthropic.com.

Window controls
---------------
    * Drag the title bar to MOVE.
    * Drag the grip in the bottom-right corner to RESIZE.
    * Click the - button (or right-click -> Minimise) to MINIMISE to the taskbar.
    * Click the x button (or right-click -> Quit) to close.
    * Right-click for: Refresh now, Minimise, Always-on-top toggle, Quit.

CLI
---
    python claude_usage_widget.py            # run the widget
    python claude_usage_widget.py --once     # print usage to stdout and exit
    python claude_usage_widget.py --selftest # build UI, fetch once, exit (CI smoke test)

Requires: requests  (pip install -r requirements.txt)
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone

import requests

try:
    import tkinter as tk
except Exception:  # pragma: no cover - headless environments
    tk = None


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
POLL_INTERVAL = 60          # seconds between refreshes
HTTP_TIMEOUT = 15           # seconds

IS_WIN = sys.platform.startswith("win")

# ---- palette (claude.ai-ish warm dark) ----
BG        = "#191917"
BG_BAR    = "#1f1e1c"
BORDER    = "#34322d"
ACCENT    = "#cc785c"
TEXT_PRI  = "#f4f1ea"
TEXT_SEC  = "#8d877d"
TEXT_DIM  = "#5a554d"
BAR_FILL  = "#cc785c"
BAR_WARN  = "#e0a458"
BAR_CRIT  = "#e2564a"
BAR_TRACK = "#2b2a26"
GREEN     = "#5dca88"
RED       = "#e2564a"

FONT_TITLE = ("Segoe UI Semibold", 10)
FONT_LABEL = ("Segoe UI", 8)
FONT_PCT   = ("Segoe UI Semibold", 9)
FONT_TINY  = ("Segoe UI", 7)
FONT_BTN   = ("Segoe UI", 11)

MIN_W, MIN_H = 230, 200


# ---------------------------------------------------------------------------
# data layer
# ---------------------------------------------------------------------------
def load_token():
    """Return (token, error). Re-read every poll so Claude Code token refreshes
    are picked up automatically."""
    if not os.path.exists(CREDENTIALS_PATH):
        return None, ("Credentials not found.\nRun Claude Code at least once, "
                      "then start this widget.")
    try:
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"Could not read credentials:\n{e}"

    oauth = data.get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token:
        return None, "No accessToken in credentials file."
    return token, None


def fetch_usage(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": OAUTH_BETA,
        "Content-Type": "application/json",
    }
    resp = requests.get(USAGE_URL, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _bucket(raw, key):
    """Normalise one usage bucket -> {'pct': float|None, 'reset': str|None}."""
    b = raw.get(key)
    if not isinstance(b, dict):
        return {"pct": None, "reset": None}
    return {"pct": b.get("utilization"), "reset": b.get("resets_at")}


def normalise(raw):
    """Map the raw API response into the shape the UI consumes."""
    return {
        "five_hour": _bucket(raw, "five_hour"),
        "seven_day": _bucket(raw, "seven_day"),
        "seven_day_opus": _bucket(raw, "seven_day_opus"),
        "seven_day_sonnet": _bucket(raw, "seven_day_sonnet"),
        "extra_usage": raw.get("extra_usage") or {},
    }


def fmt_reset(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = dt - datetime.now(timezone.utc)
        total = delta.total_seconds()
        if total < 0:
            return "now"
        mins = int(total // 60)
        hrs, mins = divmod(mins, 60)
        days, hrs = divmod(hrs, 24)
        if days > 0:
            return f"{days}d {hrs}h"
        if hrs > 0:
            return f"{hrs}h {mins}m"
        return f"{mins}m"
    except Exception:
        return iso_str[:16]


# ---------------------------------------------------------------------------
# windows taskbar / minimise helpers (no-ops off Windows)
# ---------------------------------------------------------------------------
if IS_WIN:
    import ctypes

    _GWL_EXSTYLE = -20
    _WS_EX_APPWINDOW = 0x00040000
    _WS_EX_TOOLWINDOW = 0x00000080
    _SW_MINIMIZE = 6

    def _hwnd(root):
        return ctypes.windll.user32.GetParent(root.winfo_id())

    def _long_funcs():
        u = ctypes.windll.user32
        try:
            return u.GetWindowLongPtrW, u.SetWindowLongPtrW
        except AttributeError:  # 32-bit Python
            return u.GetWindowLongW, u.SetWindowLongW

    def enable_taskbar(root):
        """Give a borderless (overrideredirect) window a real taskbar button so
        it can be minimised and restored."""
        get_long, set_long = _long_funcs()
        h = _hwnd(root)
        style = get_long(h, _GWL_EXSTYLE)
        style = (style & ~_WS_EX_TOOLWINDOW) | _WS_EX_APPWINDOW
        set_long(h, _GWL_EXSTYLE, style)
        root.withdraw()
        root.after(10, root.deiconify)

    def minimize(root):
        ctypes.windll.user32.ShowWindow(_hwnd(root), _SW_MINIMIZE)
else:  # pragma: no cover
    def enable_taskbar(root):
        pass

    def minimize(root):
        root.iconify()


# ---------------------------------------------------------------------------
# UI widgets
# ---------------------------------------------------------------------------
class Bar:
    """A horizontal progress bar drawn on a canvas so it scales on resize."""

    def __init__(self, parent):
        self.canvas = tk.Canvas(parent, height=9, bg=BG, highlightthickness=0, bd=0)
        self.pct = 0.0
        self.color = BAR_FILL
        self.canvas.bind("<Configure>", lambda e: self._draw())

    def pack(self, **kw):
        self.canvas.pack(**kw)

    def set(self, pct, color):
        self.pct = max(0.0, min(100.0, float(pct or 0)))
        self.color = color
        self._draw()

    def _rrect(self, x1, y1, x2, y2, r, fill):
        if x2 - x1 < 2 * r:
            r = max(0, (x2 - x1) / 2)
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        self.canvas.create_polygon(pts, smooth=True, fill=fill, outline=fill)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 2 or h <= 2:
            return
        r = h / 2
        self._rrect(0, 0, w, h, r, BAR_TRACK)
        if self.pct > 0:
            fw = max(h, w * self.pct / 100.0)
            self._rrect(0, 0, fw, h, r, self.color)


class UsageBlock:
    """Title + percent + bar + reset line for one usage bucket."""

    def __init__(self, parent, title):
        self.frame = tk.Frame(parent, bg=BG)
        top = tk.Frame(self.frame, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=title, font=FONT_LABEL, fg=TEXT_SEC, bg=BG).pack(side="left")
        self.pct_lbl = tk.Label(top, text="--", font=FONT_PCT, fg=TEXT_PRI, bg=BG)
        self.pct_lbl.pack(side="right")
        self.bar = Bar(self.frame)
        self.bar.pack(fill="x", pady=(3, 2))
        self.reset_lbl = tk.Label(self.frame, text="", font=FONT_TINY,
                                  fg=TEXT_DIM, bg=BG, anchor="w")
        self.reset_lbl.pack(fill="x")

    def pack(self, **kw):
        self.frame.pack(**kw)

    def update(self, bucket):
        pct = bucket.get("pct")
        if pct is None:
            self.pct_lbl.config(text="n/a", fg=TEXT_DIM)
            self.bar.set(0, BAR_TRACK)
            self.reset_lbl.config(text="not tracked on this plan")
            return
        color = BAR_CRIT if pct >= 90 else BAR_WARN if pct >= 75 else BAR_FILL
        self.pct_lbl.config(text=f"{pct:.0f}%", fg=color)
        self.bar.set(pct, color)
        reset = fmt_reset(bucket.get("reset"))
        self.reset_lbl.config(text=f"resets in {reset}" if reset else "")


class UsageWidget:
    def __init__(self, root):
        self.root = root
        self.topmost = True
        self.polling = True

        root.title("Claude Usage")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        root.configure(bg=BORDER)
        root.geometry(f"260x278+60+60")
        root.minsize(MIN_W, MIN_H)

        self._build_ui()
        self._make_menu()

        if IS_WIN:
            root.after(60, lambda: enable_taskbar(root))
        root.bind("<Map>", self._on_map)

        # background polling
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ---- layout ----
    def _build_ui(self):
        # 1px border via the root bg showing through this inset frame
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        # title bar (drag to move)
        bar = tk.Frame(shell, bg=BG, height=26)
        bar.pack(fill="x")
        self.dot = tk.Label(bar, text="●", font=("Segoe UI", 8),
                            fg=TEXT_DIM, bg=BG)
        self.dot.pack(side="left", padx=(10, 4))
        tk.Label(bar, text="Claude usage", font=FONT_TITLE,
                 fg=TEXT_PRI, bg=BG).pack(side="left")

        self._btn(bar, "✕", self._quit).pack(side="right", padx=(0, 6))
        self._btn(bar, "–", self._minimise).pack(side="right")
        self.clock = tk.Label(bar, text="", font=FONT_TINY, fg=TEXT_DIM, bg=BG)
        self.clock.pack(side="right", padx=6)

        for w in (bar,):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        # also allow dragging from the title labels
        for child in bar.winfo_children():
            if isinstance(child, tk.Label) and child not in (self.clock,):
                child.bind("<ButtonPress-1>", self._drag_start)
                child.bind("<B1-Motion>", self._drag_move)

        tk.Frame(shell, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(shell, bg=BG, padx=12, pady=10)
        body.pack(fill="both", expand=True)

        self.b_session = UsageBlock(body, "Session · 5-hour window")
        self.b_session.pack(fill="x")
        self.b_weekly = UsageBlock(body, "Weekly · all models")
        self.b_weekly.pack(fill="x", pady=(10, 0))
        self.b_opus = UsageBlock(body, "Weekly · Opus")
        self.b_sonnet = UsageBlock(body, "Weekly · Sonnet")
        # opus/sonnet are packed dynamically only when the plan reports them

        # footer
        tk.Frame(shell, bg=BORDER, height=1).pack(fill="x")
        foot = tk.Frame(shell, bg=BG, height=20)
        foot.pack(fill="x")
        self.extra_lbl = tk.Label(foot, text="", font=FONT_TINY, fg=TEXT_SEC, bg=BG)
        self.extra_lbl.pack(side="left", padx=10, pady=2)
        grip = tk.Label(foot, text="◢", font=("Segoe UI", 9),
                        fg=TEXT_DIM, bg=BG, cursor="size_nw_se")
        grip.pack(side="right", padx=4)
        grip.bind("<ButtonPress-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)

        # error overlay text (lives in body, shown only on error)
        self.err_lbl = tk.Label(body, text="", font=FONT_TINY, fg=RED, bg=BG,
                                wraplength=230, justify="left")

    def _btn(self, parent, glyph, cmd):
        b = tk.Label(parent, text=glyph, font=FONT_BTN, fg=TEXT_SEC, bg=BG,
                     cursor="hand2", padx=6)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(fg=TEXT_PRI))
        b.bind("<Leave>", lambda e: b.config(fg=TEXT_SEC))
        return b

    def _make_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=BG, fg=TEXT_PRI,
                    activebackground=ACCENT, activeforeground="#ffffff", bd=0)
        m.add_command(label="Refresh now", command=self._refresh_async)
        m.add_command(label="Minimise", command=self._minimise)
        m.add_command(label="Always on top: ON", command=self._toggle_topmost)
        m.add_separator()
        m.add_command(label="Quit", command=self._quit)
        self.menu = m
        self.root.bind("<Button-3>", lambda e: m.tk_popup(e.x_root, e.y_root))

    # ---- move ----
    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    # ---- resize ----
    def _resize_start(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rw = self.root.winfo_width()
        self._rh = self.root.winfo_height()

    def _resize_move(self, e):
        w = max(MIN_W, self._rw + (e.x_root - self._rx))
        h = max(MIN_H, self._rh + (e.y_root - self._ry))
        self.root.geometry(f"{w}x{h}")

    # ---- minimise / topmost ----
    def _minimise(self):
        minimize(self.root)

    def _on_map(self, _e):
        # re-assert the borderless, always-on-top state after restoring
        if self.topmost:
            self.root.attributes("-topmost", True)

    def _toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.menu.entryconfig(2, label=f"Always on top: {'ON' if self.topmost else 'OFF'}")

    # ---- polling ----
    def _poll_loop(self):
        while self.polling:
            self._do_fetch()
            for _ in range(POLL_INTERVAL):
                if not self.polling:
                    return
                time.sleep(1)

    def _refresh_async(self):
        threading.Thread(target=self._do_fetch, daemon=True).start()

    def _do_fetch(self):
        token, err = load_token()
        if err:
            self._post(self._show_error, err)
            return
        try:
            data = normalise(fetch_usage(token))
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            msg = f"HTTP {code}"
            if code == 401:
                msg = "Token expired. Open Claude Code to refresh, then wait a minute."
            self._post(self._show_error, msg)
        except requests.exceptions.RequestException as e:
            self._post(self._show_error, f"Network error:\n{e}")
        except Exception as e:
            self._post(self._show_error, f"Error: {e}")
        else:
            self._post(self._apply, data)

    def _post(self, fn, arg):
        try:
            self.root.after(0, fn, arg)
        except RuntimeError:
            pass  # shutting down

    # ---- render ----
    def _apply(self, data):
        self.err_lbl.pack_forget()
        self.b_session.update(data["five_hour"])
        self.b_weekly.update(data["seven_day"])

        for block, key in ((self.b_opus, "seven_day_opus"),
                            (self.b_sonnet, "seven_day_sonnet")):
            if data[key].get("pct") is not None:
                if not block.frame.winfo_ismapped():
                    block.pack(fill="x", pady=(10, 0))
                block.update(data[key])
            else:
                block.frame.pack_forget()

        ex = data.get("extra_usage") or {}
        if ex.get("is_enabled"):
            used = ex.get("used_credits") or 0
            limit = ex.get("monthly_limit") or 0
            cur = ex.get("currency") or "$"
            sym = "$" if cur in ("USD", "$", None) else f"{cur} "
            self.extra_lbl.config(text=f"Extra usage: {sym}{used:.2f} / {sym}{limit:.2f}")
        else:
            self.extra_lbl.config(text="Extra usage: off")

        self.dot.config(fg=GREEN)
        self.clock.config(text=datetime.now().strftime("%H:%M"))

    def _show_error(self, msg):
        self.dot.config(fg=RED)
        self.err_lbl.config(text=msg)
        self.err_lbl.pack(fill="x", pady=(8, 0))

    def _quit(self):
        self.polling = False
        self.root.destroy()


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def run_once():
    """Print parsed usage to stdout (no GUI)."""
    token, err = load_token()
    if err:
        print("ERROR:", err.replace("\n", " "))
        return 1
    data = normalise(fetch_usage(token))
    def line(name, b):
        pct = b.get("pct")
        if pct is None:
            print(f"  {name:<22} n/a")
        else:
            print(f"  {name:<22} {pct:5.1f}%   resets in {fmt_reset(b.get('reset'))}")
    print("Claude usage")
    line("Session (5-hour)", data["five_hour"])
    line("Weekly (all models)", data["seven_day"])
    line("Weekly (Opus)", data["seven_day_opus"])
    line("Weekly (Sonnet)", data["seven_day_sonnet"])
    ex = data.get("extra_usage") or {}
    print(f"  Extra usage:           {'on' if ex.get('is_enabled') else 'off'}")
    return 0


def main():
    args = sys.argv[1:]
    if "--once" in args:
        sys.exit(run_once())

    if tk is None:
        print("tkinter is not available in this Python build.", file=sys.stderr)
        sys.exit(2)

    root = tk.Tk()
    app = UsageWidget(root)

    if "--selftest" in args:
        # CI smoke test: fetch once on the main thread, then exit.
        root.after(200, app._do_fetch)
        root.after(2500, app._quit)

    root.mainloop()


if __name__ == "__main__":
    main()
