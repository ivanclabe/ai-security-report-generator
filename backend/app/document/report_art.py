"""Graphic elements of the client's reference report, drawn in code (no stock images).

* header band  -- gray band with the Invotecsa logo (white) and "Informe de Gestión SOC"
* cover art    -- the dark-green / teal sweeping curves over a dark "network" area
* objective art-- the teal-ringed circle next to the objective
* service tiles-- teal icon circles over gray labels (one per service in the data)
* charts       -- bar / grouped bar / horizontal bar / radar / line in the reference's palette

Everything returns PNG bytes; charts are drawn only from the values they receive.
"""
import io
import math
import textwrap
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle, Wedge
from PIL import Image

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
for _font_file in (ASSETS_DIR / "fonts").glob("Poppins-*.ttf"):
    font_manager.fontManager.addfont(str(_font_file))
INVOTECSA_LOGO = ASSETS_DIR / "invotecsa_logo.png"

DARK_GREEN = "#00532A"
TEAL = "#1A9C96"
TEAL_DARK = "#0F7D78"
GRAY_BAND = "#7A7A7A"
TILE_GRAY = "#7F7F7F"
CHART_BORDER = "#D0D0D0"
TEXT_GRAY = "#595959"


def _png(fig, *, transparent: bool = False) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, transparent=transparent, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


@lru_cache
def _white_logo() -> Image.Image | None:
    if not INVOTECSA_LOGO.exists():
        return None
    logo = Image.open(INVOTECSA_LOGO).convert("RGBA")
    white = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    white.putalpha(logo.getchannel("A"))
    return white


@lru_cache
def header_band(width_in: float = 8.5, height_in: float = 0.95) -> bytes:
    fig = plt.figure(figsize=(width_in, height_in))
    fig.patch.set_facecolor(GRAY_BAND)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width_in)
    ax.set_ylim(0, height_in)
    ax.axis("off")
    logo = _white_logo()
    if logo is not None:
        logo_h = height_in * 0.62
        logo_w = logo_h * logo.width / logo.height
        ax.imshow(logo, extent=(1.2, 1.2 + logo_w, (height_in - logo_h) / 2, (height_in + logo_h) / 2), zorder=2)
    ax.text(width_in - 1.15, height_in / 2, "Informe de Gestión SOC", ha="right", va="center", fontsize=14,
            color="#1A1A1A", fontfamily="Poppins", fontweight="medium")
    return _png(fig)


def _network(ax, x0, x1, y0, y1, seed: int, density: int = 26):
    import random

    rng = random.Random(seed)
    points = [(rng.uniform(x0, x1), rng.uniform(y0, y1)) for _ in range(density)]
    for i, (px, py) in enumerate(points):
        for qx, qy in points[i + 1:]:
            if math.dist((px, py), (qx, qy)) < (x1 - x0) * 0.16:
                ax.plot([px, qx], [py, qy], color="#8FB8D8", alpha=0.25, lw=0.6, zorder=2)
        ax.add_patch(Circle((px, py), 0.022 * (x1 - x0) / 8, color="#CFE3F5", alpha=0.7, zorder=3))
    return points


def _padlock(ax, cx, cy, r, alpha=0.9):
    ax.add_patch(Circle((cx, cy), r, fill=False, ec="white", lw=1.6, alpha=alpha * 0.8, zorder=4))
    body_w, body_h = r * 0.9, r * 0.7
    ax.add_patch(FancyBboxPatch((cx - body_w / 2, cy - body_h * 0.75), body_w, body_h,
                                boxstyle="round,pad=0.0,rounding_size=0.03", fc="white", ec="none", alpha=alpha, zorder=5))
    ax.add_patch(Wedge((cx, cy - body_h * 0.75 + body_h), body_w * 0.32, 0, 180, width=body_w * 0.1, fc="white",
                       alpha=alpha, zorder=5))


@lru_cache
def cover_art(width_in: float = 8.5, height_in: float = 6.4) -> bytes:
    fig = plt.figure(figsize=(width_in, height_in))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width_in)
    ax.set_ylim(0, height_in)
    ax.axis("off")

    # dark "network" area at the bottom, under the curves
    steps = 40
    for i in range(steps):
        y = height_in * 0.62 * i / steps
        shade = 0.08 + 0.14 * i / steps
        ax.add_patch(Rectangle((0, y), width_in, height_in * 0.62 / steps + 0.01,
                               color=(shade * 0.55, shade * 0.75, shade * 1.15), zorder=1))
    _network(ax, 0.1, width_in - 0.1, 0.1, height_in * 0.55, seed=7, density=34)
    for cx, cy, r in [(1.1, 2.1, 0.42), (4.2, 1.1, 0.5), (6.2, 2.6, 0.55), (7.7, 1.2, 0.36), (2.3, 0.7, 0.3)]:
        _padlock(ax, cx, cy, r)

    # the sweeping bands: white, dark green, white gap, teal
    xs = [width_in * i / 200 for i in range(201)]

    def curve(depth, lift):
        return [height_in * 0.62 + lift - depth * math.sin(math.pi * (x / width_in) * 0.95 + 0.15) for x in xs]

    top = [height_in] * len(xs)
    white_edge = curve(1.55, 0.95)
    green_edge = curve(1.70, 0.55)
    gap_edge = curve(1.70, 0.38)
    teal_edge = curve(1.80, 0.05)
    ax.add_patch(Polygon(list(zip(xs, white_edge)) + list(zip(reversed(xs), top)), closed=True, color="white", zorder=6))
    ax.add_patch(Polygon(list(zip(xs, green_edge)) + list(zip(reversed(xs), reversed(white_edge))), closed=True,
                         color=DARK_GREEN, zorder=6))
    ax.add_patch(Polygon(list(zip(xs, gap_edge)) + list(zip(reversed(xs), reversed(green_edge))), closed=True,
                         color="white", zorder=6))
    ax.add_patch(Polygon(list(zip(xs, teal_edge)) + list(zip(reversed(xs), reversed(gap_edge))), closed=True,
                         color=TEAL, zorder=6))
    return _png(fig)


@lru_cache
def objective_art(size_in: float = 2.6) -> bytes:
    fig = plt.figure(figsize=(size_in, size_in))
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.axis("off")
    ax.add_patch(Circle((0, 0), 0.98, color=TEAL, zorder=1))
    ax.add_patch(Circle((0, 0), 0.86, color="#10233A", zorder=2))
    ax.add_patch(Circle((-0.15, -0.1), 0.62, color="#1E4C73", alpha=0.6, zorder=2))
    import random

    rng = random.Random(3)
    pts = [(rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7)) for _ in range(22)]
    pts = [p for p in pts if math.hypot(*p) < 0.75]
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            if math.dist(p, q) < 0.42:
                ax.plot([p[0], q[0]], [p[1], q[1]], color="#9CC9EC", alpha=0.45, lw=0.8, zorder=3)
        ax.add_patch(Circle(p, 0.025, color="#D9ECFA", zorder=4))
    # shield
    shield = [(0, 0.42), (0.3, 0.3), (0.27, -0.05), (0, -0.38), (-0.27, -0.05), (-0.3, 0.3)]
    ax.add_patch(Polygon(shield, closed=True, fc="none", ec="white", lw=2.2, zorder=5))
    _padlock(ax, 0, 0.02, 0.17, alpha=1)
    return _png(fig, transparent=True)


def _icon(ax, kind: str, cx: float, cy: float, r: float):
    style = {"color": "white", "lw": 1.6, "zorder": 5}
    if kind == "red":  # globe with users
        ax.add_patch(Circle((cx, cy), r * 0.45, fill=False, ec="white", lw=1.6, zorder=5))
        ax.plot([cx - r * 0.45, cx + r * 0.45], [cy, cy], **style)
        ax.add_patch(Wedge((cx, cy), r * 0.45, 90, 270, width=0.0001, ec="white", lw=1.2, zorder=5))
        for dx, dy in [(-0.62, 0.42), (0.62, 0.42), (0, -0.72)]:
            ax.add_patch(Circle((cx + dx * r, cy + dy * r), r * 0.1, color="white", zorder=5))
    elif kind == "correo":  # envelope with lock
        w, h = r * 1.1, r * 0.7
        ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, fill=False, ec="white", lw=1.6, zorder=5))
        ax.plot([cx - w / 2, cx, cx + w / 2], [cy + h / 2, cy - h * 0.05, cy + h / 2], **style)
        _padlock(ax, cx + w * 0.38, cy + h * 0.55, r * 0.22, alpha=1)
    elif kind == "intel":  # shield with alert
        shield = [(cx, cy + r * 0.6), (cx + r * 0.45, cy + r * 0.42), (cx + r * 0.4, cy - r * 0.1), (cx, cy - r * 0.6),
                  (cx - r * 0.4, cy - r * 0.1), (cx - r * 0.45, cy + r * 0.42)]
        ax.add_patch(Polygon(shield, closed=True, fc="none", ec="white", lw=1.6, zorder=5))
        ax.plot([cx, cx], [cy + r * 0.25, cy - r * 0.1], **style)
        ax.add_patch(Circle((cx, cy - r * 0.25), r * 0.05, color="white", zorder=5))
    else:  # SIEM and others: monitor with chart
        w, h = r * 1.1, r * 0.72
        ax.add_patch(Rectangle((cx - w / 2, cy - h / 2 + r * 0.1), w, h, fill=False, ec="white", lw=1.6, zorder=5))
        ax.plot([cx - w * 0.35, cx - w * 0.1, cx + w * 0.08, cx + w * 0.35],
                [cy - h * 0.1, cy + h * 0.15, cy - h * 0.05, cy + h * 0.3], **style)
        ax.plot([cx - w * 0.2, cx + w * 0.2], [cy - h / 2 - r * 0.05, cy - h / 2 - r * 0.05], **style)


_ICON_OF_SERVICE = {"Antígeno de Red": "red", "Antígeno de Correo": "correo", "Inteligencia de Amenazas": "intel"}


def service_tiles(services: tuple[str, ...]) -> bytes:
    n = max(len(services), 1)
    width = min(6.3, 1.6 * n)
    fig = plt.figure(figsize=(width, 1.85))
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, n)
    ax.set_ylim(0, 1.85 / (width / n))
    ax.set_aspect("equal")
    ax.axis("off")
    for i, service in enumerate(services):
        cx = i + 0.5
        ax.add_patch(FancyBboxPatch((i + 0.08, 0.05), 0.84, 0.5, boxstyle="round,pad=0,rounding_size=0.08",
                                    fc=TILE_GRAY, ec="none", zorder=1))
        ax.text(cx, 0.28, "\n".join(textwrap.wrap(service, 13)), ha="center", va="center", color="white",
                fontsize=9.5, fontfamily="Poppins", fontweight="bold", zorder=2)
        ax.add_patch(Circle((cx, 0.88), 0.3, color=TEAL, zorder=3))
        _icon(ax, _ICON_OF_SERVICE.get(service, "siem"), cx, 0.88, 0.3)
    return _png(fig, transparent=True)


# ---- charts --------------------------------------------------------------------------------------


def _frame(fig):
    fig.patch.set_facecolor("white")
    fig.patch.set_edgecolor(CHART_BORDER)
    fig.patch.set_linewidth(1.6)


def _style_axes(ax):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#BFBFBF")
    ax.tick_params(colors=TEXT_GRAY, labelsize=8.5, length=0)


def chart(kind: str, title: str, categories: list[str], series: list[dict], *, width: float, height: float,
          x_label: str | None = None, y_label: str | None = None) -> bytes:
    fig = plt.figure(figsize=(width, height))
    _frame(fig)
    if kind == "radar":
        ax = fig.add_axes([0.2, 0.1, 0.6, 0.72], polar=True)
        n = len(categories)
        angles = [2 * math.pi * i / n for i in range(n)] + [0]
        for s in series:
            values = list(s["values"]) + [s["values"][0]]
            ax.plot(angles, values, color="#5B9BD5", lw=1.3, marker="o", ms=3)
            ax.fill(angles, values, color=f"#{s['color']}", alpha=0.55)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(["\n".join(textwrap.wrap(c, 22)) for c in categories], fontsize=6.8, color=TEXT_GRAY)
        ax.tick_params(axis="y", labelsize=6.5, colors=TEXT_GRAY)
        ax.set_theta_offset(math.pi / 2)
        ax.set_theta_direction(-1)
        ax.grid(color="#D9D9D9", lw=0.6)
        fig.legend(handles=[Rectangle((0, 0), 1, 1, fc=f"#{series[0]['color']}", ec="#5B9BD5")],
                   labels=[series[0]["name"]], loc="upper center", fontsize=8, frameon=False)
        return _png(fig)

    ax = fig.add_axes([0.1, 0.2, 0.86, 0.62])
    fig.suptitle(title, fontsize=11.5, color=TEXT_GRAY, fontweight="bold", y=0.95)
    if kind == "bar":
        s = series[0]
        bars = ax.bar(categories, s["values"], color=f"#{s['color']}", width=0.32)
        top = max(s["values"] or [0]) or 1
        for bar, value in zip(bars, s["values"], strict=False):
            inside = value > top * 0.25
            ax.text(bar.get_x() + bar.get_width() / 2, value * (0.5 if inside else 1) + (0 if inside else top * 0.02),
                    f"{int(value)}", ha="center", va="center" if inside else "bottom",
                    color="white" if inside else TEXT_GRAY, fontweight="bold", fontsize=9)
        # keep the bar slim when only one or two months have data
        ax.set_xlim(-0.5 - max(0, 3 - len(categories)) / 2, len(categories) - 0.5 + max(0, 3 - len(categories)) / 2)
        ax.yaxis.grid(color="#E7E6E6", lw=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", labelsize=8)
        fig.legend(handles=[Rectangle((0, 0), 1, 1, color=f"#{s['color']}")], labels=[s["name"]], loc="lower center",
                   fontsize=8, frameon=False)
    elif kind == "grouped_bar":
        n = len(series)
        width_bar = 0.8 / n
        positions = list(range(len(categories)))
        top = max((v for s in series for v in s["values"]), default=0) or 1
        for i, s in enumerate(series):
            xs = [p - 0.4 + width_bar * (i + 0.5) for p in positions]
            bars = ax.bar(xs, s["values"], width=width_bar * 0.85, color=f"#{s['color']}", label=s["name"])
            for bar, value in zip(bars, s["values"], strict=False):
                ax.text(bar.get_x() + bar.get_width() / 2, value + top * 0.02, f"{int(value)}", ha="center",
                        va="bottom", fontsize=7.5, color=TEXT_GRAY)
        ax.set_xticks(positions)
        ax.set_xticklabels(["\n".join(textwrap.wrap(c, 10)) for c in categories], fontsize=6.8)
        ax.set_yticks([])
        fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.9), ncol=n, fontsize=7.5, frameon=False)
    elif kind == "hbar":
        s = series[0]
        ax.set_position([0.33, 0.06, 0.6, 0.78])
        ys = list(range(len(categories)))[::-1]
        bars = ax.barh(ys, s["values"], color=f"#{s['color']}", height=0.38)
        ax.set_yticks(ys)
        ax.set_yticklabels(categories, fontsize=8.5)
        top = max(s["values"] or [0]) or 1
        for bar, value in zip(bars, s["values"], strict=False):
            ax.text(value + top * 0.02, bar.get_y() + bar.get_height() / 2, f"{int(value)}", va="center", fontsize=8,
                    color=TEXT_GRAY)
        ax.set_xticks([])
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_visible(True)
        ax.spines["left"].set_color("#BFBFBF")
    elif kind == "line":
        s = series[0]
        xs = list(range(len(categories)))
        ax.plot(xs, s["values"], color=f"#{s['color']}", lw=1.2, marker="o", ms=2.5)
        ax.fill_between(xs, s["values"], color=f"#{s['color']}", alpha=0.12)
        step = max(1, round(len(categories) / 11))
        months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        labels = [f"{c[8:10]}-{months[int(c[5:7]) - 1]}" if len(c) == 10 and c[4] == "-" else c for c in categories]
        ax.set_xticks(xs[::step])
        ax.set_xticklabels(labels[::step], rotation=0, fontsize=7)
        ax.set_position([0.1, 0.22, 0.86, 0.58])
        ax.yaxis.grid(color="#EDEDED", lw=0.7)
        ax.xaxis.grid(color="#F3F3F3", lw=0.5)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", labelsize=7)
        fig.legend(handles=[Rectangle((0, 0), 1, 1, fc=f"#{s['color']}", alpha=0.3, ec=f"#{s['color']}")],
                   labels=[s["name"]], loc="upper center", bbox_to_anchor=(0.5, 0.9), fontsize=7, frameon=False)
    _style_axes(ax)
    if x_label:
        ax.set_xlabel(x_label, fontsize=8, color=TEXT_GRAY)
    if y_label:
        ax.set_ylabel(y_label, fontsize=8, color=TEXT_GRAY)
    return _png(fig)
