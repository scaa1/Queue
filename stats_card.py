# stats_card.py
"""
Premium esports-style stats card renderer for VLL Queues.
Generates dark-themed player stat cards using Pillow and matplotlib.

Design philosophy:
- Strong visual hierarchy with dominant MMR display
- Dynamic accent colors from Discord role colors
- Minimal, clean, competitive feel
- Horizontal progress bars for position ELOs
- Compact stat grid with color-coded values
- Integrated rating history graph
"""

import io
import math
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ── Color Palette (premium dark theme) ──
BG_COLOR = (15, 17, 21)          # #0F1115
CARD_BG = (26, 29, 36)           # #1A1D24
CARD_LIGHTER = (35, 38, 46)      # #23262E
CARD_BORDER = (45, 48, 58)       # #2D303A
TEXT_WHITE = (229, 231, 235)      # #E5E7EB
TEXT_GRAY = (156, 163, 175)       # #9CA3AF
TEXT_MUTED = (107, 114, 128)      # #6B7280
ACCENT_BLUE = (70, 130, 240)
ACCENT_GREEN = (34, 197, 94)     # #22C55E
ACCENT_RED = (239, 68, 68)       # #EF4444
ACCENT_GOLD = (255, 200, 60)
ACCENT_PURPLE = (160, 100, 240)
ACCENT_CYAN = (80, 200, 220)
WIN_COLOR = (34, 197, 94)        # #22C55E
LOSS_COLOR = (239, 68, 68)       # #EF4444
GRAPH_LINE = (70, 130, 240)
GRAPH_FILL = (70, 130, 240, 40)
GRAPH_BG = (15, 17, 21)

# Default accent when no role color is provided
DEFAULT_ACCENT = (70, 130, 240)

# Compare mode colors
COMPARE_COLOR_1 = (70, 130, 240)   # Blue for player 1
COMPARE_COLOR_2 = (240, 160, 60)   # Orange for player 2

# Multi-line graph colors
REGULAR_LINE_COLOR = (70, 130, 240)      # Blue for regular queue
HIGHRANK_LINE_COLOR = (240, 80, 180)     # Pink for high rank queue
COMPARE_REG_COLOR = (240, 160, 60)       # Orange for compare regular
COMPARE_HR_COLOR = (160, 100, 240)       # Purple for compare high rank

# Per-position line colors for rating history
POS_DS_COLOR = (70, 130, 240)       # Blue for Defense Specialist
POS_FS_COLOR = (240, 160, 60)       # Orange for Front Spiker
POS_S_COLOR = (34, 197, 94)         # Green for Setter
POS_L_COLOR = (240, 80, 180)        # Pink for Libero
POS_HR_COLOR = (160, 100, 240)      # Purple for High Rank avg


def _get_font(size, bold=False):
    """Get a font, falling back to default if needed."""
    try:
        if bold:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except (OSError, IOError):
        try:
            if bold:
                return ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", size)
            return ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", size)
        except (OSError, IOError):
            return ImageFont.load_default()


def _draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _draw_progress_bar(draw, x, y, width, height, progress, color_left, color_right=None, bg_color=CARD_LIGHTER):
    """Draw a progress bar with gradient-like fill."""
    _draw_rounded_rect(draw, (x, y, x + width, y + height), radius=height // 2, fill=bg_color)
    if progress > 0:
        fill_width = max(height, int(width * min(progress, 1.0)))
        _draw_rounded_rect(draw, (x, y, x + fill_width, y + height), radius=height // 2, fill=color_left)


def _draw_tier_markers(draw, bar_x, bar_y, bar_w, bar_h, min_range, max_range, tier_roles):
    """Draw small vertical tick marks at tier role thresholds on a progress bar."""
    if not tier_roles or max_range <= min_range:
        return
    for tr in tier_roles:
        thresh = tr[1]
        if min_range <= thresh <= max_range:
            pos_ratio = (thresh - min_range) / (max_range - min_range)
            marker_x = bar_x + int(bar_w * pos_ratio)
            tier_color = tr[4] if len(tr) > 4 and tr[4] else CARD_BORDER
            # Use dimmed tier color for marker visibility
            marker_color = _dim_color(tier_color, 0.6) if tier_color != CARD_BORDER else CARD_BORDER
            draw.line([(marker_x, bar_y - 3), (marker_x, bar_y + bar_h + 3)],
                      fill=marker_color, width=2)


def _dim_color(color, factor=0.3):
    """Create a dimmed version of a color for backgrounds/glows."""
    return tuple(int(c * factor) for c in color[:3])


def _alpha_blend(color, alpha=0.15):
    """Create an RGBA tuple with alpha for overlays."""
    return (*color[:3], int(255 * alpha))


def _draw_glow_line(draw, y, width, color, padding=20):
    """Draw a subtle horizontal accent line with glow effect."""
    dim = _dim_color(color, 0.4)
    draw.line([(padding, y), (width - padding, y)], fill=dim, width=1)


def _generate_rating_graph_multiline(
    history_regular=None,
    history_highrank=None,
    compare_regular=None,
    compare_highrank=None,
    name1=None,
    name2=None,
    width=700,
    height=200,
    accent_color=None,
    # Per-position history for detailed lines
    history_ds=None,
    history_fs=None,
    history_s=None,
    history_l=None,
    # Per-position high rank history
    history_hr_ds=None,
    history_hr_fs=None,
    history_hr_s=None,
    history_hr_l=None,
):
    """Generate a multi-line rating history graph.

    Lines (per-position mode when position histories are provided):
    - DS (blue), FS (orange), S (green), L (pink) — solid lines
    - HR DS (blue), HR FS (orange), HR S (green), HR L (pink) — dashed lines
    Or legacy mode:
    - Regular queue (accent color or blue)
    - High rank queue (pink) - if data exists
    - Compare regular (orange) - if comparing
    - Compare high rank (purple) - if comparing
    """
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor('#%02x%02x%02x' % GRAPH_BG)
    ax.set_facecolor('#%02x%02x%02x' % GRAPH_BG)

    has_data = False
    lines_info = []  # (history, color, label, linestyle)

    # Check if we have per-position data
    has_position_data = any(h and len(h) >= 1 for h in [history_ds, history_fs, history_s, history_l])
    has_hr_position_data = any(h and len(h) >= 1 for h in [history_hr_ds, history_hr_fs, history_hr_s, history_hr_l])

    if has_position_data or has_hr_position_data:
        # Per-position lines (solid for regular)
        pos_histories = [
            (history_ds, POS_DS_COLOR, "DS"),
            (history_fs, POS_FS_COLOR, "FS"),
            (history_s, POS_S_COLOR, "S"),
            (history_l, POS_L_COLOR, "L"),
        ]
        for hist, color, label in pos_histories:
            if hist and len(hist) >= 1:
                lines_info.append((hist, color, label, '-'))

        # Per-position high rank lines (dashed, same colors with "HR" prefix)
        hr_pos_histories = [
            (history_hr_ds, POS_DS_COLOR, "HR DS"),
            (history_hr_fs, POS_FS_COLOR, "HR FS"),
            (history_hr_s, POS_S_COLOR, "HR S"),
            (history_hr_l, POS_L_COLOR, "HR L"),
        ]
        for hist, color, label in hr_pos_histories:
            if hist and len(hist) >= 1:
                lines_info.append((hist, color, label, '--'))
    else:
        # Legacy mode: single regular + high rank lines
        reg_color = accent_color if accent_color else REGULAR_LINE_COLOR

        if history_regular and len(history_regular) >= 1:
            reg_label_prefix = f"{name1} " if name1 and (compare_regular or compare_highrank) else ""
            reg_label_name = name1 if name1 and not (compare_regular or compare_highrank) else "Regular"
            lines_info.append((history_regular, reg_color, f"{reg_label_prefix}{reg_label_name}", '-'))

        if history_highrank and len(history_highrank) >= 1:
            hr_label_prefix = f"{name1} " if name1 and (compare_regular or compare_highrank) else ""
            hr_label_name = f"HR {name1}" if name1 and not (compare_regular or compare_highrank) else "High Rank"
            lines_info.append((history_highrank, HIGHRANK_LINE_COLOR, f"{hr_label_prefix}{hr_label_name}", '--'))

        if compare_regular and len(compare_regular) >= 1:
            lines_info.append((compare_regular, COMPARE_REG_COLOR, f"{name2} Regular" if name2 else "Compare Regular", '-'))

        if compare_highrank and len(compare_highrank) >= 1:
            lines_info.append((compare_highrank, COMPARE_HR_COLOR, f"{name2} High Rank" if name2 else "Compare HR", '--'))

    for history, color, label, linestyle in lines_info:
        has_data = True
        elos = [h[3] for h in history]  # elo_before values
        elos.append(history[-1][4])  # add final elo_after
        game_nums = list(range(len(elos)))

        color_hex = '#%02x%02x%02x' % color[:3]
        ax.plot(game_nums, elos, color=color_hex, linewidth=2, label=label, linestyle=linestyle, zorder=3)
        ax.fill_between(game_nums, elos, alpha=0.08, color=color_hex, zorder=2)

    if not has_data:
        ax.text(0.5, 0.5, 'Not enough data',
                ha='center', va='center', color='#%02x%02x%02x' % TEXT_MUTED,
                fontsize=10, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        # Always show legend with color labels
        legend = ax.legend(loc='upper left', fontsize=7, framealpha=0.7,
                          facecolor='#%02x%02x%02x' % CARD_BG,
                          edgecolor='#%02x%02x%02x' % CARD_BORDER)
        for text in legend.get_texts():
            text.set_color('#%02x%02x%02x' % TEXT_WHITE)

        ax.tick_params(colors='#%02x%02x%02x' % TEXT_MUTED, labelsize=7)
        ax.yaxis.tick_right()
        ax.set_xticks([])
        ax.grid(True, axis='y', alpha=0.08, color='#%02x%02x%02x' % TEXT_MUTED, linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color('#%02x%02x%02x' % CARD_BORDER)
            spine.set_linewidth(0.5)

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


def _generate_rating_graph(elo_history, width=700, height=180, color=GRAPH_LINE):
    """Generate a single-line rating history graph as a PIL Image (legacy fallback)."""
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor('#%02x%02x%02x' % GRAPH_BG)
    ax.set_facecolor('#%02x%02x%02x' % GRAPH_BG)

    if not elo_history or len(elo_history) < 2:
        ax.text(0.5, 0.5, 'Not enough match data for graph',
                ha='center', va='center', color='#%02x%02x%02x' % TEXT_MUTED,
                fontsize=10, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        elos = [h[3] for h in elo_history]
        elos.append(elo_history[-1][4])
        game_nums = list(range(len(elos)))

        color_hex = '#%02x%02x%02x' % color[:3]
        ax.plot(game_nums, elos, color=color_hex, linewidth=2, zorder=3)
        ax.fill_between(game_nums, elos, alpha=0.15, color=color_hex, zorder=2)

        min_elo = min(elos)
        max_elo = max(elos)
        if max_elo > min_elo:
            ax.axhline(y=max_elo, color=color_hex, alpha=0.3, linestyle='--', linewidth=0.8)
            ax.axhline(y=min_elo, color=color_hex, alpha=0.3, linestyle='--', linewidth=0.8)

        ax.set_xlim(0, len(elos) - 1)
        padding = max((max_elo - min_elo) * 0.15, 10)
        ax.set_ylim(min_elo - padding, max_elo + padding)

        ax.tick_params(colors='#%02x%02x%02x' % TEXT_MUTED, labelsize=8)
        ax.yaxis.tick_right()
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_color('#%02x%02x%02x' % CARD_BORDER)
            spine.set_linewidth(0.5)

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


def _generate_compare_graph(history1, history2, name1, name2, width=700, height=200):
    """Generate a comparison rating graph with two lines."""
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor('#%02x%02x%02x' % GRAPH_BG)
    ax.set_facecolor('#%02x%02x%02x' % GRAPH_BG)

    has_data = False

    for history, color, name in [(history1, COMPARE_COLOR_1, name1), (history2, COMPARE_COLOR_2, name2)]:
        if history and len(history) >= 2:
            has_data = True
            elos = [h[3] for h in history]
            elos.append(history[-1][4])
            game_nums = list(range(len(elos)))
            color_hex = '#%02x%02x%02x' % color[:3]
            ax.plot(game_nums, elos, color=color_hex, linewidth=2, label=name, zorder=3)
            ax.fill_between(game_nums, elos, alpha=0.1, color=color_hex, zorder=2)

    if not has_data:
        ax.text(0.5, 0.5, 'Not enough match data for graph',
                ha='center', va='center', color='#%02x%02x%02x' % TEXT_MUTED,
                fontsize=10, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        legend = ax.legend(loc='upper left', fontsize=8, framealpha=0.6,
                          facecolor='#%02x%02x%02x' % CARD_BG,
                          edgecolor='#%02x%02x%02x' % CARD_BORDER)
        for text in legend.get_texts():
            text.set_color('#%02x%02x%02x' % TEXT_WHITE)
        ax.tick_params(colors='#%02x%02x%02x' % TEXT_MUTED, labelsize=8)
        ax.yaxis.tick_right()
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_color('#%02x%02x%02x' % CARD_BORDER)
            spine.set_linewidth(0.5)

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


def _format_number(n):
    """Format a number with K suffix if large."""
    if n >= 10000:
        return f"{n / 1000:.1f}K"
    return str(n)


async def generate_stats_card(
    username: str,
    avatar_bytes: Optional[bytes],
    # 6v6 stats
    ds_elo: int, fs_elo: int, s_elo: int, l_elo: int,
    games: int, wins: int, losses: int,
    ds_games: int, fs_games: int, s_games: int, l_games: int,
    win_streak: int, loss_streak: int,
    best_win_streak: int, best_loss_streak: int,
    # Rank info
    rank_position: int, total_players: int,
    rank_role_name: Optional[str] = None,
    rank_role_color: Optional[Tuple] = None,
    rank_role_threshold: Optional[int] = None,
    next_rank_threshold: Optional[int] = None,
    # 2v2 / 3v3 stats
    stats_2v2: Optional[Tuple] = None,
    stats_3v3: Optional[Tuple] = None,
    # High rank stats
    hr_stats: Optional[Tuple] = None,
    hr_2v2: Optional[Tuple] = None,
    hr_3v3: Optional[Tuple] = None,
    # ELO history for graph (legacy single-line)
    elo_history: Optional[List] = None,
    # Multi-line history
    elo_history_regular: Optional[List] = None,
    elo_history_highrank: Optional[List] = None,
    # Per-position ELO history
    elo_history_ds: Optional[List] = None,
    elo_history_fs: Optional[List] = None,
    elo_history_s: Optional[List] = None,
    elo_history_l: Optional[List] = None,
    # Per-position high rank ELO history
    elo_history_hr_ds: Optional[List] = None,
    elo_history_hr_fs: Optional[List] = None,
    elo_history_hr_s: Optional[List] = None,
    elo_history_hr_l: Optional[List] = None,
    # Per-queue ELO history
    elo_history_2v2: Optional[List] = None,
    elo_history_3v3: Optional[List] = None,
    elo_history_hr_2v2: Optional[List] = None,
    elo_history_hr_3v3: Optional[List] = None,
    # Recent matches
    recent_matches: Optional[List] = None,
    # 5v5 mode
    is_5v5: bool = False,
    starting_elo: int = 650,
    # Streaks for 2v2/3v3
    streaks_2v2: Optional[Tuple] = None,
    streaks_3v3: Optional[Tuple] = None,
    # Queue focus mode (regular, 2v2, 3v3)
    queue_focus: str = "regular",
    # Tier roles for progress bars: (role_name, threshold, next_threshold, queue_type, role_color)
    tier_roles: Optional[List] = None,
    # High rank position games (for per-position HR display)
    hr_ds_games: int = 0,
    hr_fs_games: int = 0,
    hr_s_games: int = 0,
    hr_l_games: int = 0,
    # Region label to display on card
    region_label: Optional[str] = None,
    # Per-position W/L: (wins, losses)
    ds_wl: Optional[Tuple] = None,
    fs_wl: Optional[Tuple] = None,
    s_wl: Optional[Tuple] = None,
    l_wl: Optional[Tuple] = None,
    # High rank per-position W/L: (wins, losses)
    hr_ds_wl: Optional[Tuple] = None,
    hr_fs_wl: Optional[Tuple] = None,
    hr_s_wl: Optional[Tuple] = None,
    hr_l_wl: Optional[Tuple] = None,
    # High rank streaks
    streaks_hr: Optional[Tuple] = None,
    streaks_hr_2v2: Optional[Tuple] = None,
    streaks_hr_3v3: Optional[Tuple] = None,
) -> io.BytesIO:
    """Generate a premium esports-style stats card image."""

    # Dynamic accent color from Discord role
    accent = rank_role_color or DEFAULT_ACCENT
    accent_dim = _dim_color(accent, 0.25)

    CARD_WIDTH = 1200
    PADDING = 28
    INNER_PAD = 18

    # ── Determine focus stats ──
    highest_pos_name = None
    highest_pos_wl = None
    if queue_focus == "2v2" and stats_2v2:
        focus_elo = stats_2v2[0]
        focus_games = stats_2v2[1]
        focus_wins = stats_2v2[2]
        focus_losses = stats_2v2[3]
        elo_label = "2v2 MMR"
    elif queue_focus == "3v3" and stats_3v3:
        focus_elo = stats_3v3[0]
        focus_games = stats_3v3[1]
        focus_wins = stats_3v3[2]
        focus_losses = stats_3v3[3]
        elo_label = "3v3 MMR"
    else:
        played_elos = []
        played_positions = []
        pos_wl_map_list = []
        if ds_games > 0 or ds_elo != starting_elo:
            played_elos.append(ds_elo)
            played_positions.append("DS")
            pos_wl_map_list.append(ds_wl or (0, 0))
        if fs_games > 0 or fs_elo != starting_elo:
            played_elos.append(fs_elo)
            played_positions.append("FS")
            pos_wl_map_list.append(fs_wl or (0, 0))
        if s_games > 0 or s_elo != starting_elo:
            played_elos.append(s_elo)
            played_positions.append("S")
            pos_wl_map_list.append(s_wl or (0, 0))
        if (l_games > 0 or l_elo != starting_elo) and not is_5v5:
            played_elos.append(l_elo)
            played_positions.append("L")
            pos_wl_map_list.append(l_wl or (0, 0))
        if played_elos:
            max_idx = played_elos.index(max(played_elos))
            focus_elo = played_elos[max_idx]
            highest_pos_name = played_positions[max_idx]
            highest_pos_wl = pos_wl_map_list[max_idx]
        else:
            focus_elo = starting_elo
            highest_pos_name = None
            highest_pos_wl = None
        focus_games = games
        focus_wins = wins
        focus_losses = losses
        elo_label = f"HIGHEST MMR ({highest_pos_name})" if highest_pos_name else "HIGHEST MMR"

    # Sanitize: ensure wins+losses don't exceed games (can happen after match edits)
    if focus_games > 0:
        if focus_wins + focus_losses > focus_games:
            focus_games = focus_wins + focus_losses
        focus_wins = min(focus_wins, focus_games)
        focus_losses = min(focus_losses, focus_games)

    mmr_text = f"{focus_elo:.0f}" if isinstance(focus_elo, float) else str(focus_elo)
    win_rate = (focus_wins / focus_games * 100) if focus_games > 0 else 0
    win_rate = min(100.0, win_rate)
    top_pct = (rank_position / total_players * 100) if total_players > 0 else 0

    # Get appropriate streaks
    if queue_focus == "2v2" and streaks_2v2:
        w_s, l_s, bw_s, bl_s = streaks_2v2
    elif queue_focus == "3v3" and streaks_3v3:
        w_s, l_s, bw_s, bl_s = streaks_3v3
    else:
        w_s, l_s, bw_s, bl_s = win_streak, loss_streak, best_win_streak, best_loss_streak

    # ── Pre-calculate height ──
    hero_h = 180
    card_height = hero_h + 16  # hero section + gap

    if queue_focus == "regular":
        pos_count = 4  # Always show 4 positions (Libero shown crossed out for 5v5)
        card_height += 28 + pos_count * 44 + 16  # position bars section (bigger tier bars)

    # Core stats — only the focused queue row
    num_stat_rows = 1
    card_height += num_stat_rows * 90 + 16  # core stats rows

    # High rank ELO numbers section — always show
    if queue_focus == "regular":
        card_height += 28 + 4 * 44 + 16  # HR position bars (4 rows)
    else:
        card_height += 70 + 16  # HR ELO numbers row

    # High rank core stats grid (always show)
    card_height += 90 + 16

    match_count = min(len(recent_matches), 5) if recent_matches else 0
    # Recent matches: header + row of card-style boxes
    card_height += 94 + 16

    card_height += 260 + 16  # graph section (bigger)

    card_height += 16  # bottom padding

    # ── Create image ──
    img = Image.new('RGB', (CARD_WIDTH, card_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_mmr = _get_font(48, bold=True)
    font_title = _get_font(20, bold=True)
    font_large = _get_font(16, bold=True)
    font_medium = _get_font(13)
    font_medium_bold = _get_font(13, bold=True)
    font_small = _get_font(11)
    font_tiny = _get_font(10)
    font_label = _get_font(9)

    # ════════════════════════════════════════════
    #  HERO SECTION - Avatar, Name, MMR, Rank
    # ════════════════════════════════════════════
    hero_y = PADDING
    _draw_rounded_rect(draw, (PADDING, hero_y, CARD_WIDTH - PADDING, hero_y + hero_h),
                       radius=14, fill=CARD_BG)

    # Subtle accent glow line at top of hero
    draw.line([(PADDING + 14, hero_y + 1), (CARD_WIDTH - PADDING - 14, hero_y + 1)],
              fill=accent, width=2)

    # Avatar (left side)
    avatar_size = 72
    avatar_x = PADDING + INNER_PAD + 8
    avatar_y = hero_y + (hero_h - avatar_size) // 2 - 6

    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).resize((avatar_size, avatar_size))
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
            # Draw ring around avatar using accent color
            ring_size = avatar_size + 4
            draw.ellipse((avatar_x - 2, avatar_y - 2, avatar_x + ring_size - 2, avatar_y + ring_size - 2),
                        outline=accent, width=2)
            img.paste(avatar_img, (avatar_x, avatar_y), mask)
        except Exception:
            draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                        fill=CARD_LIGHTER, outline=accent, width=2)
    else:
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                    fill=CARD_LIGHTER, outline=accent, width=2)

    # Player name
    name_x = avatar_x + avatar_size + 16
    name_y = hero_y + 18
    draw.text((name_x, name_y), username, fill=TEXT_WHITE, font=font_title)

    # Region badge (if specified)
    if region_label:
        name_bbox = draw.textbbox((0, 0), username, font=font_title)
        name_w = name_bbox[2] - name_bbox[0]
        region_text = f"[{region_label}]"
        draw.text((name_x + name_w + 8, name_y + 3), region_text, fill=ACCENT_CYAN, font=font_medium_bold)

    # Tier badge with role color (only for regular queue — rank roles are 6v6-based)
    if queue_focus == "regular":
        if rank_role_name and rank_role_name != "Unranked":
            rank_label = rank_role_name
            rank_label_color = accent
        else:
            # Check if player qualifies for the lowest tier (starting ELO role)
            rank_label = "Unranked"
            rank_label_color = TEXT_MUTED
            if tier_roles:
                sorted_tr = sorted(tier_roles, key=lambda t: t[1])
                if sorted_tr:
                    first_tier = sorted_tr[0]
                    first_tier_name = first_tier[0]
                    first_tier_thresh = first_tier[1]
                    first_tier_color = first_tier[4] if len(first_tier) > 4 and first_tier[4] else None
                    # If player's ELO meets the lowest tier threshold, show that tier
                    if focus_elo >= first_tier_thresh:
                        rank_label = first_tier_name
                        rank_label_color = first_tier_color or accent
                    else:
                        # Show target tier name
                        rank_label = f"Unranked \u2192 {first_tier_name}"
        draw.text((name_x, name_y + 26), rank_label, fill=rank_label_color, font=font_medium_bold)

        # Rank placement
        if rank_position > 0 and total_players > 0:
            rank_text = f"#{rank_position}"
            if top_pct <= 0.1:
                pct_text = "Top 0.1%"
            elif top_pct <= 1:
                pct_text = f"Top {top_pct:.1f}%"
            elif top_pct <= 10:
                pct_text = f"Top {top_pct:.0f}%"
            else:
                pct_text = f"Top {top_pct:.0f}%"
            placement_text = f"{rank_text}  {pct_text}"
            draw.text((name_x, name_y + 44), placement_text, fill=TEXT_GRAY, font=font_small)
    else:
        # For non-regular queues, show queue type label instead of rank
        queue_label_text = f"{queue_focus.upper()} Queue"
        draw.text((name_x, name_y + 26), queue_label_text, fill=TEXT_GRAY, font=font_medium_bold)

    # Tier progress bar (small, under placement — only for regular queue)
    show_progress_bar = queue_focus == "regular" and (rank_role_threshold is not None or (next_rank_threshold is not None and tier_roles))
    if show_progress_bar:
        bar_x = name_x
        bar_y_pos = name_y + 62
        bar_w = 180
        bar_h = 6
        played_elos_calc = []
        if ds_games > 0 or ds_elo != starting_elo: played_elos_calc.append(ds_elo)
        if fs_games > 0 or fs_elo != starting_elo: played_elos_calc.append(fs_elo)
        if s_games > 0 or s_elo != starting_elo: played_elos_calc.append(s_elo)
        if (l_games > 0 or l_elo != starting_elo) and not is_5v5: played_elos_calc.append(l_elo)
        highest_elo_calc = max(played_elos_calc) if played_elos_calc else starting_elo
        if rank_role_threshold is not None and next_rank_threshold and next_rank_threshold > rank_role_threshold:
            progress = (highest_elo_calc - rank_role_threshold) / (next_rank_threshold - rank_role_threshold)
            progress = max(0, min(1, progress))
        elif rank_role_threshold is None and next_rank_threshold:
            # Below all tiers - show progress toward first tier from starting_elo
            progress = (highest_elo_calc - starting_elo) / (next_rank_threshold - starting_elo) if next_rank_threshold > starting_elo else 0
            progress = max(0, min(1, progress))
        else:
            progress = 1.0
        _draw_progress_bar(draw, bar_x, bar_y_pos, bar_w, bar_h, progress, accent,
                          bg_color=_dim_color(accent, 0.15))
        low_label = str(rank_role_threshold) if rank_role_threshold is not None else str(starting_elo)
        draw.text((bar_x, bar_y_pos + 9), low_label, fill=TEXT_MUTED, font=font_label)
        if next_rank_threshold:
            # Find the next tier's name to show what the bar unlocks
            next_tier_label = str(next_rank_threshold)
            if tier_roles:
                sorted_tr = sorted(tier_roles, key=lambda t: t[1])
                for tr in sorted_tr:
                    if tr[1] == next_rank_threshold:
                        next_tier_label = f"{tr[0]} ({next_rank_threshold})"
                        break
            t_bbox = draw.textbbox((0, 0), next_tier_label, font=font_label)
            draw.text((bar_x + bar_w - (t_bbox[2] - t_bbox[0]), bar_y_pos + 9),
                      next_tier_label, fill=TEXT_MUTED, font=font_label)
        elif rank_role_name and rank_role_name != "Unranked":
            # At max tier
            max_label = f"{rank_role_name} (MAX)"
            m_bbox = draw.textbbox((0, 0), max_label, font=font_label)
            draw.text((bar_x + bar_w - (m_bbox[2] - m_bbox[0]), bar_y_pos + 9),
                      max_label, fill=accent, font=font_label)

    # ── DOMINANT MMR NUMBER (right side) ──
    mmr_bbox = draw.textbbox((0, 0), mmr_text, font=font_mmr)
    mmr_w = mmr_bbox[2] - mmr_bbox[0]
    mmr_h = mmr_bbox[3] - mmr_bbox[1]
    mmr_x = CARD_WIDTH - PADDING - INNER_PAD - mmr_w - 8
    mmr_y = hero_y + 10

    # MMR number in accent color
    draw.text((mmr_x, mmr_y), mmr_text, fill=accent, font=font_mmr)

    # Label below MMR
    label_bbox = draw.textbbox((0, 0), elo_label, font=font_small)
    label_w = label_bbox[2] - label_bbox[0]
    draw.text((mmr_x + mmr_w - label_w, mmr_y + mmr_h + 12), elo_label, fill=TEXT_MUTED, font=font_small)

    # Win/Loss compact display below label (overall queue W/L)
    wl_text = f"{focus_wins}W  {focus_losses}L"
    wl_bbox = draw.textbbox((0, 0), wl_text, font=font_small)
    wl_w = wl_bbox[2] - wl_bbox[0]
    draw.text((mmr_x + mmr_w - wl_w, mmr_y + mmr_h + 28), wl_text, fill=TEXT_GRAY, font=font_small)

    y_cursor = hero_y + hero_h + 16

    # ════════════════════════════════════════════
    #  CORE STATS ROW (only the focused queue)
    # ════════════════════════════════════════════
    # Build list of queue stat data: (label, wr, wins, losses, games, ws, ls, bws, bls)
    queue_stat_rows = []

    if queue_focus == "2v2":
        s2_g = stats_2v2[1] if stats_2v2 else 0
        s2_w = stats_2v2[2] if stats_2v2 else 0
        s2_l = stats_2v2[3] if stats_2v2 else 0
        if s2_g > 0 and s2_w + s2_l > s2_g:
            s2_g = s2_w + s2_l
        s2_wr = min(100.0, (s2_w / s2_g * 100) if s2_g > 0 else 0)
        s2_ws = streaks_2v2[0] if streaks_2v2 else 0
        s2_ls = streaks_2v2[1] if streaks_2v2 else 0
        s2_bws = streaks_2v2[2] if streaks_2v2 else 0
        s2_bls = streaks_2v2[3] if streaks_2v2 else 0
        queue_stat_rows.append(("2V2", s2_wr, s2_w, s2_l, s2_g,
                                s2_ws, s2_ls, s2_bws, s2_bls))
    elif queue_focus == "3v3":
        s3_g = stats_3v3[1] if stats_3v3 else 0
        s3_w = stats_3v3[2] if stats_3v3 else 0
        s3_l = stats_3v3[3] if stats_3v3 else 0
        if s3_g > 0 and s3_w + s3_l > s3_g:
            s3_g = s3_w + s3_l
        s3_wr = min(100.0, (s3_w / s3_g * 100) if s3_g > 0 else 0)
        s3_ws = streaks_3v3[0] if streaks_3v3 else 0
        s3_ls = streaks_3v3[1] if streaks_3v3 else 0
        s3_bws = streaks_3v3[2] if streaks_3v3 else 0
        s3_bls = streaks_3v3[3] if streaks_3v3 else 0
        queue_stat_rows.append(("3V3", s3_wr, s3_w, s3_l, s3_g,
                                s3_ws, s3_ls, s3_bws, s3_bls))
    else:
        # Use sanitized focus values (wins+losses may exceed games after match edits)
        reg_g = focus_games
        reg_w = focus_wins
        reg_l = focus_losses
        regular_wr = min(100.0, (reg_w / reg_g * 100) if reg_g > 0 else 0)
        queue_stat_rows.append(("REGULAR", regular_wr, reg_w, reg_l, reg_g,
                                win_streak, loss_streak, best_win_streak, best_loss_streak))

    for qi, (q_label, q_wr, q_w, q_l, q_g, q_ws, q_ls, q_bws, q_bls) in enumerate(queue_stat_rows):
        stats_h = 80
        _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + stats_h),
                           radius=10, fill=CARD_BG)

        # Queue label in top-left corner
        draw.text((PADDING + INNER_PAD, y_cursor + 4), q_label, fill=accent, font=font_label)

        stat_items = [
            ("WIN RATE", f"{q_wr:.1f}%", WIN_COLOR if q_wr >= 50 else LOSS_COLOR),
            ("WINS", str(q_w), WIN_COLOR),
            ("LOSSES", str(q_l), LOSS_COLOR),
            ("GAMES", str(q_g), TEXT_WHITE),
            ("W STREAK", str(q_ws), WIN_COLOR if q_ws > 0 else TEXT_MUTED),
            ("L STREAK", str(q_ls), LOSS_COLOR if q_ls > 0 else TEXT_MUTED),
        ]

        stat_count = len(stat_items)
        stat_w = (CARD_WIDTH - 2 * PADDING) // stat_count

        for i, (label, value, color) in enumerate(stat_items):
            cx = PADDING + i * stat_w + stat_w // 2

            if i > 0:
                sep_x = PADDING + i * stat_w
                draw.line([(sep_x, y_cursor + 18), (sep_x, y_cursor + stats_h - 14)],
                          fill=CARD_BORDER, width=1)

            l_bbox = draw.textbbox((0, 0), label, font=font_label)
            l_w = l_bbox[2] - l_bbox[0]
            draw.text((cx - l_w // 2, y_cursor + 16), label, fill=TEXT_MUTED, font=font_label)

            v_bbox = draw.textbbox((0, 0), value, font=font_large)
            v_w = v_bbox[2] - v_bbox[0]
            draw.text((cx - v_w // 2, y_cursor + 32), value, fill=color, font=font_large)

            if label == "WIN RATE":
                sub = f"{q_w}W / {q_l}L"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "W STREAK":
                sub = f"best: {q_bws}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "L STREAK":
                sub = f"best: {q_bls}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)

        y_cursor += stats_h + 10

    # ════════════════════════════════════════════
    #  POSITION ELO BARS (tier-based level-up bars)
    # ════════════════════════════════════════════
    if queue_focus == "regular":
        positions = [
            ("DS", "Defense Specialist", ds_elo, ds_games, False, ds_wl or (0, 0)),
            ("FS", "Front Spiker", fs_elo, fs_games, False, fs_wl or (0, 0)),
            ("S", "Setter", s_elo, s_games, False, s_wl or (0, 0)),
            ("L", "Libero", l_elo, l_games, is_5v5, l_wl or (0, 0)),  # crossed out for 5v5 regions
        ]

        pos_row_h = 44
        pos_section_h = 24 + len(positions) * pos_row_h + 4
        _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + pos_section_h),
                           radius=10, fill=CARD_BG)

        draw.text((PADDING + INNER_PAD, y_cursor + 6), "POSITION ELO", fill=TEXT_MUTED, font=font_label)

        for i, (abbrev, full_name, elo, gp, crossed_out, pos_wl) in enumerate(positions):
            py = y_cursor + 24 + i * pos_row_h

            if crossed_out:
                label_x = PADDING + INNER_PAD
                draw.text((label_x, py + 8), abbrev, fill=TEXT_MUTED, font=font_medium_bold)
                elo_x = PADDING + INNER_PAD + 32
                draw.text((elo_x, py + 8), "N/A", fill=TEXT_MUTED, font=font_medium_bold)
                strike_y = py + 16
                draw.line([(PADDING + INNER_PAD, strike_y), (CARD_WIDTH - PADDING - INNER_PAD, strike_y)],
                          fill=TEXT_MUTED, width=1)
                na_text = "5v5"
                na_bbox = draw.textbbox((0, 0), na_text, font=font_small)
                na_w = na_bbox[2] - na_bbox[0]
                draw.text((CARD_WIDTH - PADDING - INNER_PAD - na_w, py + 8), na_text,
                          fill=TEXT_MUTED, font=font_small)
                continue

            # Find current and next tier for this position's ELO
            current_tier_name = None
            current_tier_color = None
            current_tier_thresh = None
            next_tier_thresh = None
            if tier_roles:
                sorted_tiers = sorted(tier_roles, key=lambda t: t[1])
                for ti, tr in enumerate(sorted_tiers):
                    role_name_t, thresh_t = tr[0], tr[1]
                    tier_color = tr[4] if len(tr) > 4 else None
                    if elo >= thresh_t:
                        current_tier_name = role_name_t
                        current_tier_color = tier_color
                        current_tier_thresh = thresh_t
                        next_tier_thresh = sorted_tiers[ti + 1][1] if ti + 1 < len(sorted_tiers) else None
                if current_tier_thresh is None and sorted_tiers:
                    # Below first tier - show progress toward first tier
                    next_tier_thresh = sorted_tiers[0][1]
                    current_tier_thresh = starting_elo

            has_data = gp > 0 or elo != starting_elo
            bar_color = current_tier_color if current_tier_color else (accent if has_data else CARD_LIGHTER)

            # Position abbreviation label
            label_x = PADDING + INNER_PAD
            draw.text((label_x, py + 4), abbrev, fill=accent if has_data else TEXT_MUTED,
                      font=font_medium_bold)

            # ELO value
            elo_text = str(elo)
            elo_x = PADDING + INNER_PAD + 32
            elo_color = TEXT_WHITE if has_data else TEXT_MUTED
            draw.text((elo_x, py + 4), elo_text, fill=elo_color, font=font_medium_bold)

            # Show tier role name after ELO value
            if current_tier_name:
                elo_bbox = draw.textbbox((0, 0), elo_text, font=font_medium_bold)
                elo_tw = elo_bbox[2] - elo_bbox[0]
                draw.text((elo_x + elo_tw + 6, py + 6), current_tier_name,
                          fill=bar_color, font=font_tiny)

            # Tier-based level-up progress bar
            bar_x = PADDING + INNER_PAD + 160
            bar_w = CARD_WIDTH - 2 * PADDING - 2 * INNER_PAD - 160 - 150
            bar_h = 14
            bar_y = py + 22

            if tier_roles:
                sorted_tiers = sorted(tier_roles, key=lambda t: t[1])

                # Show progress within current tier range (start → next tier)
                if current_tier_thresh is not None and next_tier_thresh and next_tier_thresh > current_tier_thresh:
                    bar_min_val = current_tier_thresh
                    bar_max_val = next_tier_thresh
                elif current_tier_thresh is None and sorted_tiers:
                    # Below first tier
                    bar_min_val = starting_elo
                    bar_max_val = sorted_tiers[0][1]
                elif current_tier_thresh is not None:
                    # At max tier - show full bar
                    bar_min_val = current_tier_thresh
                    bar_max_val = current_tier_thresh + 100
                else:
                    bar_min_val = starting_elo
                    bar_max_val = starting_elo + 200

                # Draw full background
                _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                   radius=bar_h // 2, fill=_dim_color(accent, 0.1))

                # Draw filled progress within the current tier range (only if player has data)
                if has_data:
                    if bar_max_val > bar_min_val:
                        progress = (elo - bar_min_val) / (bar_max_val - bar_min_val)
                        progress = max(0.02, min(1, progress))
                    else:
                        progress = 1.0
                    fill_width = max(bar_h, int(bar_w * progress))
                    _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                       radius=bar_h // 2, fill=bar_color)

                # Show threshold labels and tier name at end of bar
                if current_tier_thresh is not None:
                    draw.text((bar_x, bar_y + bar_h + 2), str(current_tier_thresh),
                              fill=TEXT_MUTED, font=font_label)
                else:
                    draw.text((bar_x, bar_y + bar_h + 2), str(starting_elo),
                              fill=TEXT_MUTED, font=font_label)
                # Next tier name at end of bar
                if next_tier_thresh:
                    # Find the next tier's name
                    next_tier_name_label = ""
                    for tr in sorted_tiers:
                        if tr[1] == next_tier_thresh:
                            next_tier_name_label = tr[0]
                            break
                    if next_tier_name_label:
                        nt_text = f"{next_tier_name_label} ({next_tier_thresh})"
                    else:
                        nt_text = str(next_tier_thresh)
                    nt_bbox = draw.textbbox((0, 0), nt_text, font=font_label)
                    nt_w = nt_bbox[2] - nt_bbox[0]
                    draw.text((bar_x + bar_w - nt_w, bar_y + bar_h + 2), nt_text,
                              fill=TEXT_MUTED, font=font_label)
                elif current_tier_name:
                    # At max tier - show current tier name at end
                    max_text = f"{current_tier_name} (MAX)"
                    max_bbox = draw.textbbox((0, 0), max_text, font=font_label)
                    max_w = max_bbox[2] - max_bbox[0]
                    draw.text((bar_x + bar_w - max_w, bar_y + bar_h + 2), max_text,
                              fill=bar_color, font=font_label)
            else:
                # No tier roles - always show bar (dimmed if no data)
                _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                   radius=bar_h // 2, fill=_dim_color(accent, 0.1))
                if has_data:
                    progress = 0.5  # Default middle position
                    fill_width = max(bar_h, int(bar_w * progress))
                    _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                       radius=bar_h // 2, fill=accent)

            # W/L and games count on the right
            p_wins, p_losses = pos_wl
            wl_gp_text = f"{p_wins}W {p_losses}L  {gp}G"
            gp_color = TEXT_GRAY
            wl_gp_bbox = draw.textbbox((0, 0), wl_gp_text, font=font_small)
            wl_gp_w = wl_gp_bbox[2] - wl_gp_bbox[0]
            draw.text((CARD_WIDTH - PADDING - INNER_PAD - wl_gp_w, py + 4), wl_gp_text,
                      fill=gp_color, font=font_small)

        y_cursor += pos_section_h + 10

    # ════════════════════════════════════════════
    #  HIGH RANK ELO (position bars for regular, inline for 2v2/3v3)
    # ════════════════════════════════════════════
    if True:  # Always show high rank section
        if queue_focus == "regular":
            # Show per-position bars like regular position section
            hr_ds = hr_stats[0] if hr_stats else starting_elo
            hr_fs = hr_stats[1] if hr_stats else starting_elo
            hr_s_val = hr_stats[2] if hr_stats else starting_elo
            hr_l_val = hr_stats[3] if hr_stats else starting_elo
            hr_positions = [
                ("DS", "Defense Specialist", hr_ds, hr_ds_games, False, hr_ds_wl or (0, 0)),
                ("FS", "Front Spiker", hr_fs, hr_fs_games, False, hr_fs_wl or (0, 0)),
                ("S", "Setter", hr_s_val, hr_s_games, False, hr_s_wl or (0, 0)),
                ("L", "Libero", hr_l_val, hr_l_games, is_5v5, hr_l_wl or (0, 0)),
            ]

            pos_row_h = 44
            hr_section_h = 24 + len(hr_positions) * pos_row_h + 4
            _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + hr_section_h),
                               radius=10, fill=CARD_BG)

            draw.text((PADDING + INNER_PAD, y_cursor + 6), "HIGH RANK", fill=TEXT_MUTED, font=font_label)

            hr_played_elos = [e for _, _, e, g, crossed, _ in hr_positions if (g > 0 or e != starting_elo) and not crossed]
            if hr_played_elos:
                highest_text = f"HIGHEST: {max(hr_played_elos)}"
                ht_bbox = draw.textbbox((0, 0), highest_text, font=font_label)
                ht_w = ht_bbox[2] - ht_bbox[0]
                draw.text((CARD_WIDTH - PADDING - INNER_PAD - ht_w, y_cursor + 6),
                          highest_text, fill=accent, font=font_label)

            for i, (abbrev, full_name, elo, gp, crossed_out, pos_wl) in enumerate(hr_positions):
                py = y_cursor + 24 + i * pos_row_h

                if crossed_out:
                    draw.text((PADDING + INNER_PAD, py + 8), abbrev, fill=TEXT_MUTED, font=font_medium_bold)
                    draw.text((PADDING + INNER_PAD + 32, py + 8), "N/A", fill=TEXT_MUTED, font=font_medium_bold)
                    draw.line([(PADDING + INNER_PAD, py + 16), (CARD_WIDTH - PADDING - INNER_PAD, py + 16)],
                              fill=TEXT_MUTED, width=1)
                    na_text = "5v5"
                    na_bbox = draw.textbbox((0, 0), na_text, font=font_small)
                    na_w = na_bbox[2] - na_bbox[0]
                    draw.text((CARD_WIDTH - PADDING - INNER_PAD - na_w, py + 8), na_text,
                              fill=TEXT_MUTED, font=font_small)
                    continue

                # Find current tier
                current_tier_name = None
                current_tier_color = None
                current_tier_thresh = None
                next_tier_thresh = None
                if tier_roles:
                    sorted_tiers = sorted(tier_roles, key=lambda t: t[1])
                    for ti, tr in enumerate(sorted_tiers):
                        if elo >= tr[1]:
                            current_tier_name = tr[0]
                            current_tier_color = tr[4] if len(tr) > 4 else None
                            current_tier_thresh = tr[1]
                            next_tier_thresh = sorted_tiers[ti + 1][1] if ti + 1 < len(sorted_tiers) else None
                    if current_tier_thresh is None and sorted_tiers:
                        next_tier_thresh = sorted_tiers[0][1]
                        current_tier_thresh = starting_elo

                has_data = gp > 0 or elo != starting_elo
                bar_color = current_tier_color if current_tier_color else (accent if has_data else CARD_LIGHTER)

                draw.text((PADDING + INNER_PAD, py + 4), abbrev,
                          fill=accent if has_data else TEXT_MUTED, font=font_medium_bold)

                elo_text = str(elo)
                draw.text((PADDING + INNER_PAD + 32, py + 4), elo_text,
                          fill=TEXT_WHITE if has_data else TEXT_MUTED, font=font_medium_bold)

                if current_tier_name:
                    elo_bbox = draw.textbbox((0, 0), elo_text, font=font_medium_bold)
                    elo_tw = elo_bbox[2] - elo_bbox[0]
                    draw.text((PADDING + INNER_PAD + 32 + elo_tw + 6, py + 6), current_tier_name,
                              fill=bar_color, font=font_tiny)

                # Tier-based level-up bar (always show)
                bar_x = PADDING + INNER_PAD + 160
                bar_w = CARD_WIDTH - 2 * PADDING - 2 * INNER_PAD - 160 - 150
                bar_h = 14
                bar_y = py + 22

                if tier_roles:
                    sorted_tiers = sorted(tier_roles, key=lambda t: t[1])

                    # Use same tier-based progress as regular bars
                    if current_tier_thresh is not None and next_tier_thresh and next_tier_thresh > current_tier_thresh:
                        bar_min_val = current_tier_thresh
                        bar_max_val = next_tier_thresh
                    elif current_tier_thresh is None and sorted_tiers:
                        bar_min_val = starting_elo
                        bar_max_val = sorted_tiers[0][1]
                    elif current_tier_thresh is not None:
                        bar_min_val = current_tier_thresh
                        bar_max_val = current_tier_thresh + 100
                    else:
                        bar_min_val = starting_elo
                        bar_max_val = starting_elo + 200

                    # Draw background
                    _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                       radius=bar_h // 2, fill=_dim_color(accent, 0.1))

                    # Draw fill only when player has data
                    if has_data:
                        if bar_max_val > bar_min_val:
                            progress = (elo - bar_min_val) / (bar_max_val - bar_min_val)
                            progress = max(0.02, min(1, progress))
                        else:
                            progress = 1.0
                        fill_width = max(bar_h, int(bar_w * progress))
                        _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                           radius=bar_h // 2, fill=bar_color)

                    # Show threshold labels
                    if current_tier_thresh is not None:
                        draw.text((bar_x, bar_y + bar_h + 2), str(current_tier_thresh),
                                  fill=TEXT_MUTED, font=font_label)
                    else:
                        draw.text((bar_x, bar_y + bar_h + 2), str(starting_elo),
                                  fill=TEXT_MUTED, font=font_label)
                    if next_tier_thresh:
                        next_tier_name_label = ""
                        for tr in sorted_tiers:
                            if tr[1] == next_tier_thresh:
                                next_tier_name_label = tr[0]
                                break
                        nt_text = f"{next_tier_name_label} ({next_tier_thresh})" if next_tier_name_label else str(next_tier_thresh)
                        nt_bbox = draw.textbbox((0, 0), nt_text, font=font_label)
                        nt_w = nt_bbox[2] - nt_bbox[0]
                        draw.text((bar_x + bar_w - nt_w, bar_y + bar_h + 2), nt_text,
                                  fill=TEXT_MUTED, font=font_label)
                    elif current_tier_name:
                        max_text = f"{current_tier_name} (MAX)"
                        max_bbox = draw.textbbox((0, 0), max_text, font=font_label)
                        max_w = max_bbox[2] - max_bbox[0]
                        draw.text((bar_x + bar_w - max_w, bar_y + bar_h + 2), max_text,
                                  fill=bar_color, font=font_label)
                else:
                    # No tier roles - always show bar (dimmed if no data)
                    _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                       radius=bar_h // 2, fill=_dim_color(accent, 0.1))
                    if has_data:
                        fill_width = max(bar_h, int(bar_w * 0.5))
                        _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                           radius=bar_h // 2, fill=accent)

                p_wins, p_losses = pos_wl
                wl_gp_text = f"{p_wins}W {p_losses}L  {gp}G"
                wl_gp_bbox = draw.textbbox((0, 0), wl_gp_text, font=font_small)
                wl_gp_w = wl_gp_bbox[2] - wl_gp_bbox[0]
                draw.text((CARD_WIDTH - PADDING - INNER_PAD - wl_gp_w, py + 4), wl_gp_text,
                          fill=TEXT_GRAY, font=font_small)

            y_cursor += hr_section_h + 10

        else:
            # 2v2/3v3 mode: inline display with W/L — always show
            hr_items = []
            if queue_focus == "2v2":
                hr_elo_val = hr_2v2[0] if hr_2v2 else starting_elo
                hr_w = hr_2v2[2] if hr_2v2 and len(hr_2v2) > 2 else 0
                hr_l = hr_2v2[3] if hr_2v2 and len(hr_2v2) > 3 else 0
                hr_items.append(("HR 2v2", str(hr_elo_val), hr_w, hr_l))
            elif queue_focus == "3v3":
                hr_elo_val = hr_3v3[0] if hr_3v3 else starting_elo
                hr_w = hr_3v3[2] if hr_3v3 and len(hr_3v3) > 2 else 0
                hr_l = hr_3v3[3] if hr_3v3 and len(hr_3v3) > 3 else 0
                hr_items.append(("HR 3v3", str(hr_elo_val), hr_w, hr_l))

            hr_section_h = 60
            _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + hr_section_h),
                               radius=10, fill=CARD_BG)
            draw.text((PADDING + INNER_PAD, y_cursor + 6), "HIGH RANK", fill=TEXT_MUTED, font=font_label)

            hr_item_count = len(hr_items)
            hr_item_w = (CARD_WIDTH - 2 * PADDING) // hr_item_count
            for i, (hr_label, hr_value, hr_w, hr_l) in enumerate(hr_items):
                cx = PADDING + i * hr_item_w + hr_item_w // 2

                if i > 0:
                    sep_x = PADDING + i * hr_item_w
                    draw.line([(sep_x, y_cursor + 14), (sep_x, y_cursor + hr_section_h - 10)],
                              fill=CARD_BORDER, width=1)

                l_bbox = draw.textbbox((0, 0), hr_label, font=font_label)
                l_w = l_bbox[2] - l_bbox[0]
                draw.text((cx - l_w // 2, y_cursor + 18), hr_label, fill=TEXT_MUTED, font=font_label)

                v_bbox = draw.textbbox((0, 0), hr_value, font=font_large)
                v_w = v_bbox[2] - v_bbox[0]
                draw.text((cx - v_w // 2, y_cursor + 31), hr_value, fill=accent, font=font_large)

                # W/L below the MMR value
                wl_text = f"{hr_w}W {hr_l}L"
                wl_bbox = draw.textbbox((0, 0), wl_text, font=font_label)
                wl_w = wl_bbox[2] - wl_bbox[0]
                draw.text((cx - wl_w // 2, y_cursor + 47), wl_text, fill=TEXT_GRAY, font=font_label)

            y_cursor += hr_section_h + 10

    # ════════════════════════════════════════════
    #  HIGH RANK CORE STATS (W/L/WR/streaks for HR queue)
    # ════════════════════════════════════════════
    hr_stat_rows = []
    if queue_focus == "regular":
        hr_g = hr_stats[4] if hr_stats and len(hr_stats) > 4 else 0
        hr_w = hr_stats[5] if hr_stats and len(hr_stats) > 5 else 0
        hr_l = hr_stats[6] if hr_stats and len(hr_stats) > 6 else 0
        hr_wr = (hr_w / hr_g * 100) if hr_g > 0 else 0
        hr_ws = streaks_hr[0] if streaks_hr else 0
        hr_ls = streaks_hr[1] if streaks_hr else 0
        hr_bws = streaks_hr[2] if streaks_hr else 0
        hr_bls = streaks_hr[3] if streaks_hr else 0
        hr_stat_rows.append(("HIGH RANK", hr_wr, hr_w, hr_l, hr_g, hr_ws, hr_ls, hr_bws, hr_bls))
    elif queue_focus == "2v2":
        hr_g = hr_2v2[1] if hr_2v2 else 0
        hr_w = hr_2v2[2] if hr_2v2 else 0
        hr_l = hr_2v2[3] if hr_2v2 else 0
        hr_wr = (hr_w / hr_g * 100) if hr_g > 0 else 0
        hr_ws = streaks_hr_2v2[0] if streaks_hr_2v2 else 0
        hr_ls = streaks_hr_2v2[1] if streaks_hr_2v2 else 0
        hr_bws = streaks_hr_2v2[2] if streaks_hr_2v2 else 0
        hr_bls = streaks_hr_2v2[3] if streaks_hr_2v2 else 0
        hr_stat_rows.append(("HR 2V2", hr_wr, hr_w, hr_l, hr_g, hr_ws, hr_ls, hr_bws, hr_bls))
    elif queue_focus == "3v3":
        hr_g = hr_3v3[1] if hr_3v3 else 0
        hr_w = hr_3v3[2] if hr_3v3 else 0
        hr_l = hr_3v3[3] if hr_3v3 else 0
        hr_wr = (hr_w / hr_g * 100) if hr_g > 0 else 0
        hr_ws = streaks_hr_3v3[0] if streaks_hr_3v3 else 0
        hr_ls = streaks_hr_3v3[1] if streaks_hr_3v3 else 0
        hr_bws = streaks_hr_3v3[2] if streaks_hr_3v3 else 0
        hr_bls = streaks_hr_3v3[3] if streaks_hr_3v3 else 0
        hr_stat_rows.append(("HR 3V3", hr_wr, hr_w, hr_l, hr_g, hr_ws, hr_ls, hr_bws, hr_bls))

    for qi, (q_label, q_wr, q_w, q_l, q_g, q_ws, q_ls, q_bws, q_bls) in enumerate(hr_stat_rows):
        stats_h = 80
        _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + stats_h),
                           radius=10, fill=CARD_BG)

        draw.text((PADDING + INNER_PAD, y_cursor + 4), q_label, fill=accent, font=font_label)

        stat_items = [
            ("WIN RATE", f"{q_wr:.1f}%", WIN_COLOR if q_wr >= 50 else LOSS_COLOR),
            ("WINS", str(q_w), WIN_COLOR),
            ("LOSSES", str(q_l), LOSS_COLOR),
            ("GAMES", str(q_g), TEXT_WHITE),
            ("W STREAK", str(q_ws), WIN_COLOR if q_ws > 0 else TEXT_MUTED),
            ("L STREAK", str(q_ls), LOSS_COLOR if q_ls > 0 else TEXT_MUTED),
        ]

        stat_count = len(stat_items)
        stat_w = (CARD_WIDTH - 2 * PADDING) // stat_count

        for i, (label, value, color) in enumerate(stat_items):
            cx = PADDING + i * stat_w + stat_w // 2

            if i > 0:
                sep_x = PADDING + i * stat_w
                draw.line([(sep_x, y_cursor + 18), (sep_x, y_cursor + stats_h - 14)],
                          fill=CARD_BORDER, width=1)

            l_bbox = draw.textbbox((0, 0), label, font=font_label)
            l_w = l_bbox[2] - l_bbox[0]
            draw.text((cx - l_w // 2, y_cursor + 16), label, fill=TEXT_MUTED, font=font_label)

            v_bbox = draw.textbbox((0, 0), value, font=font_large)
            v_w = v_bbox[2] - v_bbox[0]
            draw.text((cx - v_w // 2, y_cursor + 32), value, fill=color, font=font_large)

            if label == "WIN RATE":
                sub = f"{q_w}W / {q_l}L"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "W STREAK":
                sub = f"best: {q_bws}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "L STREAK":
                sub = f"best: {q_bls}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 54), sub, fill=TEXT_MUTED, font=font_label)

        y_cursor += stats_h + 10

    # ════════════════════════════════════════════
    #  RECENT GAMES (card-style boxes)
    # ════════════════════════════════════════════
    matches_h = 88

    _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + matches_h),
                       radius=10, fill=CARD_BG)

    draw.text((PADDING + INNER_PAD, y_cursor + 6), "RECENT GAMES", fill=TEXT_MUTED, font=font_label)

    if recent_matches:
        box_y = y_cursor + 22
        content_w = CARD_WIDTH - 2 * PADDING - 2 * INNER_PAD
        num_matches = min(len(recent_matches), 5)
        box_gap = 8
        box_w = (content_w - (num_matches - 1) * box_gap) // num_matches
        box_h = 48

        for i, match in enumerate(recent_matches[:5]):
            match_id, is_win, elo_change, position = match
            bx = PADDING + INNER_PAD + i * (box_w + box_gap)

            badge_color = WIN_COLOR if is_win else LOSS_COLOR
            # Box background with colored border
            _draw_rounded_rect(draw, (bx, box_y, bx + box_w, box_y + box_h),
                               radius=6, fill=_dim_color(badge_color, 0.15),
                               outline=_dim_color(badge_color, 0.4), width=1)

            # Top line: W/L badge + ELO change (centered)
            badge_text = "WIN" if is_win else "LOSS"
            change_text = f"+{elo_change}" if elo_change >= 0 else str(elo_change)
            top_text = f"{badge_text}  {change_text}"
            top_bbox = draw.textbbox((0, 0), top_text, font=font_medium_bold)
            top_w = top_bbox[2] - top_bbox[0]
            draw.text((bx + (box_w - top_w) // 2, box_y + 6), top_text,
                      fill=badge_color, font=font_medium_bold)

            # Bottom line: Position/queue type (centered)
            if position:
                pos_abbrev = str(position)
                pos_map = {
                    "Defense Specialist": "DS",
                    "Front Spiker": "FS",
                    "Setter": "S",
                    "Libero": "L",
                    "highrank": "High Rank",
                    "highrank_2v2": "HR 2v2",
                    "highrank_3v3": "HR 3v3",
                    "2v2": "2v2",
                    "3v3": "3v3",
                    "6v6": "6v6",
                    "player": queue_focus.upper() if queue_focus in ("2v2", "3v3") else "6v6",
                    "Player": queue_focus.upper() if queue_focus in ("2v2", "3v3") else "6v6",
                }
                pos_abbrev = pos_map.get(pos_abbrev, pos_abbrev)
                pa_bbox = draw.textbbox((0, 0), pos_abbrev, font=font_small)
                pa_w = pa_bbox[2] - pa_bbox[0]
                draw.text((bx + (box_w - pa_w) // 2, box_y + 27), pos_abbrev,
                          fill=TEXT_GRAY, font=font_small)
    else:
        draw.text((PADDING + INNER_PAD, y_cursor + 36), "No recent matches",
                  fill=TEXT_MUTED, font=font_small)

    y_cursor += matches_h + 10

    # ════════════════════════════════════════════
    #  RATING HISTORY GRAPH
    # ════════════════════════════════════════════
    graph_section_h = 250
    _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + graph_section_h),
                       radius=10, fill=CARD_BG)

    draw.text((PADDING + INNER_PAD, y_cursor + 6), "RATING HISTORY", fill=TEXT_MUTED, font=font_label)

    graph_w = CARD_WIDTH - 2 * PADDING - 2 * INNER_PAD
    graph_h = 210

    # Use role color for graph line
    graph_color = accent

    # Check for per-position history data (regular + high rank)
    has_pos_history = any(h and len(h) >= 1 for h in [elo_history_ds, elo_history_fs, elo_history_s, elo_history_l])
    has_hr_pos_history = any(h and len(h) >= 1 for h in [elo_history_hr_ds, elo_history_hr_fs, elo_history_hr_s, elo_history_hr_l])

    if queue_focus == "2v2":
        # 2v2 queue: show 2v2 rating history + highrank 2v2
        graph_img = _generate_rating_graph_multiline(
            history_regular=elo_history_2v2,
            history_highrank=elo_history_hr_2v2,
            width=graph_w,
            height=graph_h,
            accent_color=graph_color,
            name1="2v2",
        )
    elif queue_focus == "3v3":
        # 3v3 queue: show 3v3 rating history + highrank 3v3
        graph_img = _generate_rating_graph_multiline(
            history_regular=elo_history_3v3,
            history_highrank=elo_history_hr_3v3,
            width=graph_w,
            height=graph_h,
            accent_color=graph_color,
            name1="3v3",
        )
    elif (has_pos_history or has_hr_pos_history) and queue_focus == "regular":
        # Per-position ELO lines (solid) + per-position HR lines (dashed)
        graph_img = _generate_rating_graph_multiline(
            width=graph_w,
            height=graph_h,
            accent_color=graph_color,
            history_ds=elo_history_ds,
            history_fs=elo_history_fs,
            history_s=elo_history_s,
            history_l=elo_history_l if not is_5v5 else None,
            history_hr_ds=elo_history_hr_ds,
            history_hr_fs=elo_history_hr_fs,
            history_hr_s=elo_history_hr_s,
            history_hr_l=elo_history_hr_l if not is_5v5 else None,
        )
    elif elo_history_regular or elo_history_highrank:
        graph_img = _generate_rating_graph_multiline(
            history_regular=elo_history_regular,
            history_highrank=elo_history_highrank,
            width=graph_w,
            height=graph_h,
            accent_color=graph_color,
        )
    else:
        graph_img = _generate_rating_graph(elo_history, width=graph_w, height=graph_h,
                                           color=graph_color)

    graph_img = graph_img.resize((graph_w, graph_h))
    img.paste(graph_img, (PADDING + INNER_PAD, y_cursor + 28))

    y_cursor += graph_section_h + 10

    # Crop to actual content height
    img = img.crop((0, 0, CARD_WIDTH, y_cursor + 4))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


async def generate_compare_card(
    player1_name: str,
    player2_name: str,
    player1_avatar: Optional[bytes],
    player2_avatar: Optional[bytes],
    # 6v6 stats (ds, fs, s, l, games, wins, losses)
    p1_stats: Optional[Tuple],
    p2_stats: Optional[Tuple],
    p1_games_per_pos: Tuple,  # (ds_games, fs_games, s_games, l_games)
    p2_games_per_pos: Tuple,
    # Rank info
    p1_rank: Tuple,  # (rank, total)
    p2_rank: Tuple,
    # 2v2/3v3 stats (elo, games, wins, losses)
    p1_2v2: Optional[Tuple] = None,
    p2_2v2: Optional[Tuple] = None,
    p1_3v3: Optional[Tuple] = None,
    p2_3v3: Optional[Tuple] = None,
    # High rank
    p1_hr: Optional[Tuple] = None,
    p2_hr: Optional[Tuple] = None,
    p1_hr_2v2: Optional[Tuple] = None,
    p2_hr_2v2: Optional[Tuple] = None,
    p1_hr_3v3: Optional[Tuple] = None,
    p2_hr_3v3: Optional[Tuple] = None,
    # ELO history
    p1_history: Optional[List] = None,
    p2_history: Optional[List] = None,
    # Multi-line history
    p1_history_regular: Optional[List] = None,
    p2_history_regular: Optional[List] = None,
    p1_history_highrank: Optional[List] = None,
    p2_history_highrank: Optional[List] = None,
    # Flags
    p1_is_5v5: bool = False,
    p2_is_5v5: bool = False,
    starting_elo: int = 650,
    # Recent matches
    p1_recent: Optional[List] = None,
    p2_recent: Optional[List] = None,
    # Rank role info
    p1_rank_role: Optional[str] = None,
    p2_rank_role: Optional[str] = None,
    p1_rank_threshold: Optional[int] = None,
    p2_rank_threshold: Optional[int] = None,
    p1_next_threshold: Optional[int] = None,
    p2_next_threshold: Optional[int] = None,
    # Queue focus mode
    queue_focus: str = "regular",
    # Streaks (ws, ls, best_ws, best_ls)
    p1_streaks_6v6: Optional[Tuple] = None,
    p2_streaks_6v6: Optional[Tuple] = None,
    p1_streaks_2v2: Optional[Tuple] = None,
    p2_streaks_2v2: Optional[Tuple] = None,
    p1_streaks_3v3: Optional[Tuple] = None,
    p2_streaks_3v3: Optional[Tuple] = None,
    # Role colors
    p1_role_color: Optional[Tuple] = None,
    p2_role_color: Optional[Tuple] = None,
    # Tier roles for progress bars
    tier_roles: Optional[List] = None,
    # High rank position games
    p1_hr_games_per_pos: Optional[Tuple] = None,  # (ds_games, fs_games, s_games, l_games)
    p2_hr_games_per_pos: Optional[Tuple] = None,
    # Per-position W/L: ((ds_w, ds_l), (fs_w, fs_l), (s_w, s_l), (l_w, l_l))
    p1_pos_wl: Optional[Tuple] = None,
    p2_pos_wl: Optional[Tuple] = None,
    # High rank per-position W/L
    p1_hr_pos_wl: Optional[Tuple] = None,
    p2_hr_pos_wl: Optional[Tuple] = None,
    # High rank streaks
    p1_streaks_hr: Optional[Tuple] = None,
    p2_streaks_hr: Optional[Tuple] = None,
    p1_streaks_hr_2v2: Optional[Tuple] = None,
    p2_streaks_hr_2v2: Optional[Tuple] = None,
    p1_streaks_hr_3v3: Optional[Tuple] = None,
    p2_streaks_hr_3v3: Optional[Tuple] = None,
) -> io.BytesIO:
    """Generate a comparison card image matching the stat card style."""

    CARD_WIDTH = 1300
    card_height = 2400  # will be cropped
    PADDING = 28
    INNER_PAD = 18
    MID_X = CARD_WIDTH // 2

    img = Image.new('RGB', (CARD_WIDTH, card_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fonts (matching stat card)
    font_mmr = _get_font(28, bold=True)
    font_title = _get_font(20, bold=True)
    font_large = _get_font(16, bold=True)
    font_medium = _get_font(13)
    font_medium_bold = _get_font(13, bold=True)
    font_small = _get_font(11)
    font_tiny = _get_font(10)
    font_label = _get_font(9)

    y_cursor = PADDING

    # ── Accent colors from role colors ──
    p1_accent = p1_role_color or COMPARE_COLOR_1
    p2_accent = p2_role_color or COMPARE_COLOR_2

    # ── Helper: highest ELO (returns elo, position_name) ──
    def _highest_elo(stats, games_per_pos, is_5v5):
        pos_names = ["DS", "FS", "S", "L"]
        if not stats:
            return starting_elo, None
        played = []
        played_pos = []
        for j in range(4):
            if (games_per_pos[j] > 0 or stats[j] != starting_elo) and not (j == 3 and is_5v5):
                played.append(stats[j])
                played_pos.append(pos_names[j])
        if played:
            max_idx = played.index(max(played))
            return played[max_idx], played_pos[max_idx]
        return starting_elo, None

    p1_highest, p1_highest_pos = _highest_elo(p1_stats, p1_games_per_pos, p1_is_5v5)
    p2_highest, p2_highest_pos = _highest_elo(p2_stats, p2_games_per_pos, p2_is_5v5)

    # ── Determine focus-specific stats ──
    if queue_focus == "2v2":
        p1_focus = p1_2v2
        p2_focus = p2_2v2
        p1_focus_streaks = p1_streaks_2v2
        p2_focus_streaks = p2_streaks_2v2
        elo_label = "2v2 MMR"
        p1_elo_label = elo_label
        p2_elo_label = elo_label
    elif queue_focus == "3v3":
        p1_focus = p1_3v3
        p2_focus = p2_3v3
        p1_focus_streaks = p1_streaks_3v3
        p2_focus_streaks = p2_streaks_3v3
        elo_label = "3v3 MMR"
        p1_elo_label = elo_label
        p2_elo_label = elo_label
    else:
        p1_focus = None
        p2_focus = None
        p1_focus_streaks = p1_streaks_6v6
        p2_focus_streaks = p2_streaks_6v6
        p1_elo_label = f"HIGHEST MMR ({p1_highest_pos})" if p1_highest_pos else "HIGHEST MMR"
        p2_elo_label = f"HIGHEST MMR ({p2_highest_pos})" if p2_highest_pos else "HIGHEST MMR"
        elo_label = "HIGHEST MMR"

    # Calculate focus ELOs and stats for each player
    if queue_focus in ("2v2", "3v3"):
        p1_elo = p1_focus[0] if p1_focus and p1_focus[1] > 0 else 0
        p2_elo = p2_focus[0] if p2_focus and p2_focus[1] > 0 else 0
        p1_g = p1_focus[1] if p1_focus else 0
        p2_g = p2_focus[1] if p2_focus else 0
        p1_w = p1_focus[2] if p1_focus else 0
        p2_w = p2_focus[2] if p2_focus else 0
        p1_l = p1_focus[3] if p1_focus else 0
        p2_l = p2_focus[3] if p2_focus else 0
    else:
        p1_elo = p1_highest
        p2_elo = p2_highest
        p1_g = p1_stats[4] if p1_stats else 0
        p2_g = p2_stats[4] if p2_stats else 0
        p1_w = p1_stats[5] if p1_stats else 0
        p2_w = p2_stats[5] if p2_stats else 0
        p1_l = p1_stats[6] if p1_stats else 0
        p2_l = p2_stats[6] if p2_stats else 0

    # Sanitize: ensure wins+losses don't exceed games (can happen after match edits)
    if p1_g > 0:
        if p1_w + p1_l > p1_g:
            p1_g = p1_w + p1_l
        p1_w = min(p1_w, p1_g)
        p1_l = min(p1_l, p1_g)
    if p2_g > 0:
        if p2_w + p2_l > p2_g:
            p2_g = p2_w + p2_l
        p2_w = min(p2_w, p2_g)
        p2_l = min(p2_l, p2_g)

    # Overall queue W/L for hero display (position-specific shown in bars below)
    p1_hero_w, p1_hero_l = p1_w, p1_l
    p2_hero_w, p2_hero_l = p2_w, p2_l

    p1_wr = min(100.0, (p1_w / p1_g * 100) if p1_g > 0 else 0)
    p2_wr = min(100.0, (p2_w / p2_g * 100) if p2_g > 0 else 0)
    p1_mmr = f"{p1_elo:.0f}" if isinstance(p1_elo, float) else str(p1_elo)
    p2_mmr = f"{p2_elo:.0f}" if isinstance(p2_elo, float) else str(p2_elo)

    # Streaks
    p1_ws = p1_focus_streaks[0] if p1_focus_streaks else 0
    p2_ws = p2_focus_streaks[0] if p2_focus_streaks else 0
    p1_ls = p1_focus_streaks[1] if p1_focus_streaks else 0
    p2_ls = p2_focus_streaks[1] if p2_focus_streaks else 0
    p1_bws = p1_focus_streaks[2] if p1_focus_streaks else 0
    p2_bws = p2_focus_streaks[2] if p2_focus_streaks else 0
    p1_bls = p1_focus_streaks[3] if p1_focus_streaks else 0
    p2_bls = p2_focus_streaks[3] if p2_focus_streaks else 0

    # ════════════════════════════════════════════
    #  HERO SECTION — Side-by-side player cards
    # ════════════════════════════════════════════
    hero_h = 220
    GAP = 12
    half_card_w = (CARD_WIDTH - 2 * PADDING - GAP) // 2

    for idx, (name, avatar_bytes, accent, mmr_text, rank_tuple, role_name,
              threshold, next_thresh, avg, wins, losses, role_color,
              player_elo_label, hero_wins, hero_losses) in enumerate([
        (player1_name, player1_avatar, p1_accent, p1_mmr, p1_rank, p1_rank_role,
         p1_rank_threshold, p1_next_threshold, p1_highest if queue_focus == "regular" else p1_elo,
         p1_w, p1_l, p1_role_color, p1_elo_label, p1_hero_w, p1_hero_l),
        (player2_name, player2_avatar, p2_accent, p2_mmr, p2_rank, p2_rank_role,
         p2_rank_threshold, p2_next_threshold, p2_highest if queue_focus == "regular" else p2_elo,
         p2_w, p2_l, p2_role_color, p2_elo_label, p2_hero_w, p2_hero_l),
    ]):
        hx = PADDING + idx * (half_card_w + GAP)
        card_center_x = hx + half_card_w // 2
        _draw_rounded_rect(draw, (hx, y_cursor, hx + half_card_w, y_cursor + hero_h),
                           radius=14, fill=CARD_BG)
        # Accent glow line at top
        draw.line([(hx + 14, y_cursor + 1), (hx + half_card_w - 14, y_cursor + 1)],
                  fill=accent, width=2)

        # Avatar (centered horizontally)
        avatar_size = 48
        avatar_x = card_center_x - avatar_size // 2
        avatar_y = y_cursor + 10
        if avatar_bytes:
            try:
                av_img = Image.open(io.BytesIO(avatar_bytes)).resize((avatar_size, avatar_size))
                mask = Image.new('L', (avatar_size, avatar_size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
                ring_size = avatar_size + 4
                draw.ellipse((avatar_x - 2, avatar_y - 2, avatar_x + ring_size - 2, avatar_y + ring_size - 2),
                            outline=accent, width=2)
                img.paste(av_img, (avatar_x, avatar_y), mask)
            except Exception:
                draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                            fill=CARD_LIGHTER, outline=accent, width=2)
        else:
            draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                        fill=CARD_LIGHTER, outline=accent, width=2)

        # Name (centered)
        name_bbox = draw.textbbox((0, 0), name, font=font_large)
        name_w = name_bbox[2] - name_bbox[0]
        name_y = avatar_y + avatar_size + 6
        draw.text((card_center_x - name_w // 2, name_y), name, fill=TEXT_WHITE, font=font_large)

        # Rank role + placement (centered on one line)
        # Rank info (only for regular queue — rank roles are 6v6-based)
        if queue_focus == "regular":
            if role_name and role_name != "Unranked":
                rank_label = role_name
            else:
                rank_label = "Unranked"
            rank_pos, total = rank_tuple
            if total > 0 and rank_pos > 0:
                pct = (rank_pos / total) * 100
                if pct <= 0.1:
                    pct_text = "Top 0.1%"
                elif pct <= 1:
                    pct_text = f"Top {pct:.1f}%"
                else:
                    pct_text = f"Top {pct:.0f}%"
                rank_info = f"{rank_label}  #{rank_pos} {pct_text}"
            else:
                rank_info = rank_label
        else:
            rank_info = f"{queue_focus.upper()} Queue"
        ri_bbox = draw.textbbox((0, 0), rank_info, font=font_small)
        ri_w = ri_bbox[2] - ri_bbox[0]
        draw.text((card_center_x - ri_w // 2, name_y + 18), rank_info, fill=accent, font=font_small)

        # Tier progress bar (centered, fixed width — only for regular queue)
        bar_w = half_card_w - 2 * INNER_PAD - 20
        bar_x = card_center_x - bar_w // 2
        bar_y_pos = name_y + 34
        bar_h = 5
        show_compare_bar = queue_focus == "regular" and (threshold is not None or (next_thresh is not None and tier_roles))
        if show_compare_bar:
            if threshold is not None and next_thresh and next_thresh > threshold:
                progress = (avg - threshold) / (next_thresh - threshold)
                progress = max(0, min(1, progress))
            elif threshold is None and next_thresh:
                # Below first tier - show progress toward first tier
                progress = (avg - starting_elo) / (next_thresh - starting_elo) if next_thresh > starting_elo else 0
                progress = max(0, min(1, progress))
            else:
                progress = 1.0
            _draw_progress_bar(draw, bar_x, bar_y_pos, bar_w, bar_h, progress, accent,
                              bg_color=_dim_color(accent, 0.15))
            low_label = str(threshold) if threshold is not None else str(starting_elo)
            draw.text((bar_x, bar_y_pos + 8), low_label, fill=TEXT_MUTED, font=font_label)
            if next_thresh:
                # Find next tier name
                next_tier_label = str(next_thresh)
                if tier_roles:
                    sorted_tr = sorted(tier_roles, key=lambda t: t[1])
                    for tr in sorted_tr:
                        if tr[1] == next_thresh:
                            next_tier_label = f"{tr[0]} ({next_thresh})"
                            break
                t_bbox = draw.textbbox((0, 0), next_tier_label, font=font_label)
                draw.text((bar_x + bar_w - (t_bbox[2] - t_bbox[0]), bar_y_pos + 8),
                          next_tier_label, fill=TEXT_MUTED, font=font_label)
            elif role_name and role_name != "Unranked":
                max_label = f"{role_name} (MAX)"
                m_bbox = draw.textbbox((0, 0), max_label, font=font_label)
                draw.text((bar_x + bar_w - (m_bbox[2] - m_bbox[0]), bar_y_pos + 8),
                          max_label, fill=accent, font=font_label)

        # Dominant MMR number (centered)
        mmr_bbox = draw.textbbox((0, 0), mmr_text, font=font_mmr)
        mmr_w = mmr_bbox[2] - mmr_bbox[0]
        mmr_h = mmr_bbox[3] - mmr_bbox[1]
        mmr_y = bar_y_pos + 30
        draw.text((card_center_x - mmr_w // 2, mmr_y), mmr_text, fill=accent, font=font_mmr)

        # Label (centered below MMR)
        label_bbox_c = draw.textbbox((0, 0), player_elo_label, font=font_label)
        label_w_c = label_bbox_c[2] - label_bbox_c[0]
        draw.text((card_center_x - label_w_c // 2, mmr_y + mmr_h + 6), player_elo_label, fill=TEXT_MUTED, font=font_label)

        # W/L (centered below label)
        wl_label = f"{hero_wins}W  {hero_losses}L"
        wl_bbox_c = draw.textbbox((0, 0), wl_label, font=font_label)
        wl_w_c = wl_bbox_c[2] - wl_bbox_c[0]
        draw.text((card_center_x - wl_w_c // 2, mmr_y + mmr_h + 20), wl_label, fill=TEXT_GRAY, font=font_label)

    y_cursor += hero_h + 10

    y_cursor += 6

    # ════════════════════════════════════════════
    #  CORE STATS ROW (only the focused queue)
    # ════════════════════════════════════════════
    # Build list of per-queue compare stat data
    compare_stat_rows = []

    def _sanitize_wl(g, w, l):
        """Ensure wins+losses don't exceed games (can happen after match edits)."""
        if g > 0 and w + l > g:
            g = w + l
        return g, min(w, g) if g > 0 else w, min(l, g) if g > 0 else l

    if queue_focus == "2v2":
        q1_g = p1_2v2[1] if p1_2v2 else 0
        q2_g = p2_2v2[1] if p2_2v2 else 0
        q1_w = p1_2v2[2] if p1_2v2 else 0
        q2_w = p2_2v2[2] if p2_2v2 else 0
        q1_l = p1_2v2[3] if p1_2v2 else 0
        q2_l = p2_2v2[3] if p2_2v2 else 0
        q1_g, q1_w, q1_l = _sanitize_wl(q1_g, q1_w, q1_l)
        q2_g, q2_w, q2_l = _sanitize_wl(q2_g, q2_w, q2_l)
        q1_wr = min(100.0, (q1_w / q1_g * 100) if q1_g > 0 else 0)
        q2_wr = min(100.0, (q2_w / q2_g * 100) if q2_g > 0 else 0)
        q1_ws = p1_streaks_2v2[0] if p1_streaks_2v2 else 0
        q2_ws = p2_streaks_2v2[0] if p2_streaks_2v2 else 0
        q1_ls = p1_streaks_2v2[1] if p1_streaks_2v2 else 0
        q2_ls = p2_streaks_2v2[1] if p2_streaks_2v2 else 0
        q1_bws = p1_streaks_2v2[2] if p1_streaks_2v2 else 0
        q2_bws = p2_streaks_2v2[2] if p2_streaks_2v2 else 0
        q1_bls = p1_streaks_2v2[3] if p1_streaks_2v2 else 0
        q2_bls = p2_streaks_2v2[3] if p2_streaks_2v2 else 0
        compare_stat_rows.append(("2V2", q1_wr, q2_wr, q1_w, q2_w, q1_l, q2_l, q1_g, q2_g,
                                  q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls))
    elif queue_focus == "3v3":
        q1_g = p1_3v3[1] if p1_3v3 else 0
        q2_g = p2_3v3[1] if p2_3v3 else 0
        q1_w = p1_3v3[2] if p1_3v3 else 0
        q2_w = p2_3v3[2] if p2_3v3 else 0
        q1_l = p1_3v3[3] if p1_3v3 else 0
        q2_l = p2_3v3[3] if p2_3v3 else 0
        q1_g, q1_w, q1_l = _sanitize_wl(q1_g, q1_w, q1_l)
        q2_g, q2_w, q2_l = _sanitize_wl(q2_g, q2_w, q2_l)
        q1_wr = min(100.0, (q1_w / q1_g * 100) if q1_g > 0 else 0)
        q2_wr = min(100.0, (q2_w / q2_g * 100) if q2_g > 0 else 0)
        q1_ws = p1_streaks_3v3[0] if p1_streaks_3v3 else 0
        q2_ws = p2_streaks_3v3[0] if p2_streaks_3v3 else 0
        q1_ls = p1_streaks_3v3[1] if p1_streaks_3v3 else 0
        q2_ls = p2_streaks_3v3[1] if p2_streaks_3v3 else 0
        q1_bws = p1_streaks_3v3[2] if p1_streaks_3v3 else 0
        q2_bws = p2_streaks_3v3[2] if p2_streaks_3v3 else 0
        q1_bls = p1_streaks_3v3[3] if p1_streaks_3v3 else 0
        q2_bls = p2_streaks_3v3[3] if p2_streaks_3v3 else 0
        compare_stat_rows.append(("3V3", q1_wr, q2_wr, q1_w, q2_w, q1_l, q2_l, q1_g, q2_g,
                                  q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls))
    else:
        compare_stat_rows.append(("REGULAR", p1_wr, p2_wr, p1_w, p2_w, p1_l, p2_l, p1_g, p2_g,
                                  p1_ws, p2_ws, p1_ls, p2_ls, p1_bws, p2_bws, p1_bls, p2_bls))

    for qi, (q_label, q1_wr, q2_wr, q1_w, q2_w, q1_l, q2_l, q1_g, q2_g,
             q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls) in enumerate(compare_stat_rows):
        stats_h = 70
        _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + stats_h),
                           radius=10, fill=CARD_BG)

        # Queue label in top-left corner
        draw.text((PADDING + INNER_PAD, y_cursor + 2), q_label, fill=p1_accent, font=font_label)

        stat_items = [
            ("WIN RATE", f"{q1_wr:.1f}%", f"{q2_wr:.1f}%",
             WIN_COLOR if q1_wr >= 50 else LOSS_COLOR, WIN_COLOR if q2_wr >= 50 else LOSS_COLOR),
            ("WINS", str(q1_w), str(q2_w), WIN_COLOR, WIN_COLOR),
            ("LOSSES", str(q1_l), str(q2_l), LOSS_COLOR, LOSS_COLOR),
            ("GAMES", str(q1_g), str(q2_g), TEXT_WHITE, TEXT_WHITE),
            ("W STREAK", str(q1_ws), str(q2_ws),
             WIN_COLOR if q1_ws > 0 else TEXT_MUTED, WIN_COLOR if q2_ws > 0 else TEXT_MUTED),
            ("L STREAK", str(q1_ls), str(q2_ls),
             LOSS_COLOR if q1_ls > 0 else TEXT_MUTED, LOSS_COLOR if q2_ls > 0 else TEXT_MUTED),
        ]

        stat_count = len(stat_items)
        stat_w = (CARD_WIDTH - 2 * PADDING) // stat_count

        for i, (label, v1, v2, c1, c2) in enumerate(stat_items):
            cx = PADDING + i * stat_w + stat_w // 2

            if i > 0:
                sep_x = PADDING + i * stat_w
                draw.line([(sep_x, y_cursor + 16), (sep_x, y_cursor + stats_h - 14)],
                          fill=CARD_BORDER, width=1)

            l_bbox = draw.textbbox((0, 0), label, font=font_label)
            l_w = l_bbox[2] - l_bbox[0]
            draw.text((cx - l_w // 2, y_cursor + 12), label, fill=TEXT_MUTED, font=font_label)

            v1_bbox = draw.textbbox((0, 0), v1, font=font_large)
            v1_w = v1_bbox[2] - v1_bbox[0]
            draw.text((cx - v1_w - 6, y_cursor + 28), v1, fill=c1, font=font_large)
            draw.text((cx - 2, y_cursor + 28), "|", fill=TEXT_MUTED, font=font_small)
            draw.text((cx + 6, y_cursor + 28), v2, fill=c2, font=font_large)

            if label == "W STREAK":
                sub = f"best: {q1_bws} | {q2_bws}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 50), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "L STREAK":
                sub = f"best: {q1_bls} | {q2_bls}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 50), sub, fill=TEXT_MUTED, font=font_label)

        y_cursor += stats_h + 10

    # ════════════════════════════════════════════
    #  POSITION ELO BARS (split: P1 left, P2 right)
    # ════════════════════════════════════════════
    if queue_focus == "regular":
        abbrevs = [("DS", "Defense Specialist"), ("FS", "Front Spiker"), ("S", "Setter"), ("L", "Libero")]

        pos_row_h = 44
        pos_section_h = 24 + len(abbrevs) * pos_row_h + 4

        GAP_POS = 12
        half_panel_w = (CARD_WIDTH - 2 * PADDING - GAP_POS) // 2

        for side, (p_stats, p_games, p_is_5v5, p_accent, p_wl_data, panel_label) in enumerate([
            (p1_stats, p1_games_per_pos, p1_is_5v5, p1_accent, p1_pos_wl, player1_name),
            (p2_stats, p2_games_per_pos, p2_is_5v5, p2_accent, p2_pos_wl, player2_name),
        ]):
            px = PADDING + side * (half_panel_w + GAP_POS)
            _draw_rounded_rect(draw, (px, y_cursor, px + half_panel_w, y_cursor + pos_section_h),
                               radius=10, fill=CARD_BG)

            draw.text((px + INNER_PAD, y_cursor + 6), "POSITION ELO", fill=TEXT_MUTED, font=font_label)

            if p_stats:
                p_elos = [p_stats[0], p_stats[1], p_stats[2], p_stats[3]]

                for i, (abbrev, full_name) in enumerate(abbrevs):
                    py = y_cursor + 24 + i * pos_row_h
                    is_lib = (i == 3)
                    elo_val = p_elos[i]
                    gp = p_games[i]
                    crossed_out = is_lib and p_is_5v5

                    if crossed_out:
                        draw.text((px + INNER_PAD, py + 8), abbrev, fill=TEXT_MUTED, font=font_medium_bold)
                        draw.text((px + INNER_PAD + 30, py + 8), "N/A", fill=TEXT_MUTED, font=font_medium_bold)
                        draw.line([(px + INNER_PAD, py + 16), (px + half_panel_w - INNER_PAD, py + 16)],
                                  fill=TEXT_MUTED, width=1)
                        na_text = "5v5"
                        na_bbox = draw.textbbox((0, 0), na_text, font=font_small)
                        na_w = na_bbox[2] - na_bbox[0]
                        draw.text((px + half_panel_w - INNER_PAD - na_w, py + 8), na_text,
                                  fill=TEXT_MUTED, font=font_small)
                        continue

                    # Find tier for this position
                    current_tier_name = None
                    current_tier_color = None
                    if tier_roles:
                        sorted_tiers = sorted(tier_roles, key=lambda t: t[1])
                        for tr in sorted_tiers:
                            if elo_val >= tr[1]:
                                current_tier_name = tr[0]
                                current_tier_color = tr[4] if len(tr) > 4 else None

                    has_data = gp > 0 or elo_val != starting_elo
                    bar_color = current_tier_color if current_tier_color else (p_accent if has_data else CARD_LIGHTER)

                    draw.text((px + INNER_PAD, py + 4), abbrev,
                              fill=p_accent if has_data else TEXT_MUTED, font=font_medium_bold)

                    elo_text = str(elo_val)
                    draw.text((px + INNER_PAD + 30, py + 4), elo_text,
                              fill=TEXT_WHITE if has_data else TEXT_MUTED, font=font_medium_bold)

                    if current_tier_name:
                        elo_bbox = draw.textbbox((0, 0), elo_text, font=font_medium_bold)
                        elo_tw = elo_bbox[2] - elo_bbox[0]
                        draw.text((px + INNER_PAD + 30 + elo_tw + 4, py + 6), current_tier_name,
                                  fill=bar_color, font=font_tiny)

                    # Tier-based level-up bar
                    bar_x = px + INNER_PAD + 80
                    bar_w = half_panel_w - 2 * INNER_PAD - 80 - 110
                    bar_h = 12
                    bar_y = py + 22

                    if tier_roles:
                        sorted_tiers = sorted(tier_roles, key=lambda t: t[1])

                        # Find current and next tier for this position
                        pos_current_thresh = None
                        pos_next_thresh = None
                        for ti, tr in enumerate(sorted_tiers):
                            if elo_val >= tr[1]:
                                pos_current_thresh = tr[1]
                                if ti + 1 < len(sorted_tiers):
                                    pos_next_thresh = sorted_tiers[ti + 1][1]

                        # Progress within current tier range
                        if pos_current_thresh is not None and pos_next_thresh and pos_next_thresh > pos_current_thresh:
                            bar_min_val = pos_current_thresh
                            bar_max_val = pos_next_thresh
                        elif pos_current_thresh is None and sorted_tiers:
                            bar_min_val = starting_elo
                            bar_max_val = sorted_tiers[0][1]
                        elif pos_current_thresh is not None:
                            bar_min_val = pos_current_thresh
                            bar_max_val = pos_current_thresh + 100
                        else:
                            bar_min_val = starting_elo
                            bar_max_val = starting_elo + 200

                        _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                           radius=bar_h // 2, fill=_dim_color(p_accent, 0.1))

                        if bar_max_val > bar_min_val:
                            progress = (elo_val - bar_min_val) / (bar_max_val - bar_min_val)
                            progress = max(0.02, min(1, progress))
                        else:
                            progress = 1.0
                        fill_width = max(bar_h, int(bar_w * progress))
                        _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                           radius=bar_h // 2, fill=bar_color)

                        # Tier label below bar
                        if pos_next_thresh:
                            next_name = ""
                            for tr in sorted_tiers:
                                if tr[1] == pos_next_thresh:
                                    next_name = tr[0]
                                    break
                            if next_name:
                                nt_text = f"{next_name} ({pos_next_thresh})"
                            else:
                                nt_text = str(pos_next_thresh)
                            nt_bbox = draw.textbbox((0, 0), nt_text, font=font_label)
                            nt_w = nt_bbox[2] - nt_bbox[0]
                            draw.text((bar_x + bar_w - nt_w, bar_y + bar_h + 1), nt_text,
                                      fill=TEXT_MUTED, font=font_label)
                        elif current_tier_name:
                            max_text = f"{current_tier_name} (MAX)"
                            max_bbox = draw.textbbox((0, 0), max_text, font=font_label)
                            max_w = max_bbox[2] - max_bbox[0]
                            draw.text((bar_x + bar_w - max_w, bar_y + bar_h + 1), max_text,
                                      fill=bar_color, font=font_label)
                    else:
                        # No tier roles - always show bar
                        _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                           radius=bar_h // 2, fill=_dim_color(p_accent, 0.1))
                        if has_data:
                            fill_width = max(bar_h, int(bar_w * 0.5))
                            _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_width, bar_y + bar_h),
                                               radius=bar_h // 2, fill=p_accent)

                    p_wins_val, p_losses_val = (0, 0)
                    if p_wl_data and i < len(p_wl_data):
                        p_wins_val, p_losses_val = p_wl_data[i]
                    wl_gp_text = f"{p_wins_val}W {p_losses_val}L {gp}G"
                    wl_gp_bbox = draw.textbbox((0, 0), wl_gp_text, font=font_small)
                    wl_gp_w = wl_gp_bbox[2] - wl_gp_bbox[0]
                    draw.text((px + half_panel_w - INNER_PAD - wl_gp_w, py + 4), wl_gp_text,
                              fill=TEXT_GRAY, font=font_small)
            else:
                draw.text((px + INNER_PAD, y_cursor + 30), "No data",
                          fill=TEXT_MUTED, font=font_medium)

        y_cursor += pos_section_h + 10

    # ════════════════════════════════════════════
    #  HIGH RANK ELO SECTION (position bars for regular, inline for 2v2/3v3)
    # ════════════════════════════════════════════
    if queue_focus == "regular":
        # Show per-position HR bars split: P1 left, P2 right (always show)
        hr_abbrevs = [("DS", "Defense Specialist"), ("FS", "Front Spiker"), ("S", "Setter"), ("L", "Libero")]

        p1_hr_gpp = p1_hr_games_per_pos or (0, 0, 0, 0)
        p2_hr_gpp = p2_hr_games_per_pos or (0, 0, 0, 0)
        p1_hr_elos = [p1_hr[0], p1_hr[1], p1_hr[2], p1_hr[3]] if p1_hr else [starting_elo] * 4
        p2_hr_elos = [p2_hr[0], p2_hr[1], p2_hr[2], p2_hr[3]] if p2_hr else [starting_elo] * 4

        pos_row_h = 36
        hr_pos_section_h = 24 + len(hr_abbrevs) * pos_row_h + 4

        GAP_HR = 12
        half_hr_w = (CARD_WIDTH - 2 * PADDING - GAP_HR) // 2

        for side, (hr_elos, hr_gpp, p_is_5v5, p_accent, hr_wl_data) in enumerate([
            (p1_hr_elos, p1_hr_gpp, p1_is_5v5, p1_accent, p1_hr_pos_wl),
            (p2_hr_elos, p2_hr_gpp, p2_is_5v5, p2_accent, p2_hr_pos_wl),
        ]):
            px = PADDING + side * (half_hr_w + GAP_HR)
            _draw_rounded_rect(draw, (px, y_cursor, px + half_hr_w, y_cursor + hr_pos_section_h),
                               radius=10, fill=CARD_BG)

            draw.text((px + INNER_PAD, y_cursor + 6), "HIGH RANK", fill=TEXT_MUTED, font=font_label)

            # ELO range for progress bars — aligned to tier thresholds
            active_hr_elos = [hr_elos[j] for j in range(4)
                              if (hr_gpp[j] > 0 or hr_elos[j] != starting_elo) and not (j == 3 and p_is_5v5)]
            if tier_roles:
                all_thresholds = sorted([tr[1] for tr in tier_roles])
                hr_min_range = all_thresholds[0]
                if len(all_thresholds) > 1:
                    avg_interval = (all_thresholds[-1] - all_thresholds[0]) / (len(all_thresholds) - 1)
                    hr_max_range = all_thresholds[-1] + int(avg_interval)
                else:
                    hr_max_range = all_thresholds[0] + 200
                if active_hr_elos:
                    hr_max_range = max(hr_max_range, max(active_hr_elos) + 30)
                    hr_min_range = min(hr_min_range, min(active_hr_elos) - 20)
            elif active_hr_elos:
                hr_min_range = min(min(active_hr_elos) - 50, starting_elo - 50)
                hr_max_range = max(max(active_hr_elos) + 50, starting_elo + 200)
            else:
                hr_min_range = starting_elo - 50
                hr_max_range = starting_elo + 200

            for i, (abbrev, full_name) in enumerate(hr_abbrevs):
                py = y_cursor + 24 + i * pos_row_h
                is_lib = (i == 3)
                elo_val = hr_elos[i]
                gp = hr_gpp[i]
                crossed_out = is_lib and p_is_5v5

                if crossed_out:
                    draw.text((px + INNER_PAD, py + 6), abbrev, fill=TEXT_MUTED, font=font_medium_bold)
                    draw.text((px + INNER_PAD + 30, py + 6), "N/A", fill=TEXT_MUTED, font=font_medium_bold)
                    strike_y = py + 14
                    draw.line([(px + INNER_PAD, strike_y), (px + half_hr_w - INNER_PAD, strike_y)],
                              fill=TEXT_MUTED, width=1)
                    na_text = "5v5"
                    na_bbox = draw.textbbox((0, 0), na_text, font=font_small)
                    na_w = na_bbox[2] - na_bbox[0]
                    draw.text((px + half_hr_w - INNER_PAD - na_w, py + 6), na_text,
                              fill=TEXT_MUTED, font=font_small)
                    continue

                has_data = gp > 0 or elo_val != starting_elo
                draw.text((px + INNER_PAD, py + 6), abbrev,
                          fill=p_accent if has_data else TEXT_MUTED, font=font_medium_bold)
                draw.text((px + INNER_PAD + 30, py + 6), str(elo_val),
                          fill=TEXT_WHITE if has_data else TEXT_MUTED, font=font_medium_bold)

                bar_x = px + INNER_PAD + 80
                bar_w = half_hr_w - 2 * INNER_PAD - 80 - 100
                bar_h = 10
                bar_y = py + 9

                if has_data and hr_max_range > hr_min_range:
                    progress = (elo_val - hr_min_range) / (hr_max_range - hr_min_range)
                    progress = max(0.02, min(1, progress))
                else:
                    progress = 0

                bar_color = p_accent if has_data else CARD_LIGHTER
                _draw_progress_bar(draw, bar_x, bar_y, bar_w, bar_h, progress, bar_color,
                                  bg_color=_dim_color(p_accent, 0.1))
                _draw_tier_markers(draw, bar_x, bar_y, bar_w, bar_h, hr_min_range, hr_max_range, tier_roles)

                # W/L and games count
                p_wins_val, p_losses_val = (0, 0)
                if hr_wl_data and i < len(hr_wl_data):
                    p_wins_val, p_losses_val = hr_wl_data[i]
                wl_gp_text = f"{p_wins_val}W {p_losses_val}L {gp}G"
                gp_color = TEXT_GRAY
                wl_gp_bbox = draw.textbbox((0, 0), wl_gp_text, font=font_small)
                wl_gp_w = wl_gp_bbox[2] - wl_gp_bbox[0]
                draw.text((px + half_hr_w - INNER_PAD - wl_gp_w, py + 6), wl_gp_text,
                          fill=gp_color, font=font_small)

        y_cursor += hr_pos_section_h + 10

    else:
        # 2v2/3v3 mode: inline display with W/L — always show
        hr_items = []
        if queue_focus == "2v2":
            p1_hr2 = p1_hr_2v2[0] if p1_hr_2v2 else starting_elo
            p2_hr2 = p2_hr_2v2[0] if p2_hr_2v2 else starting_elo
            p1_hr2_wl = (p1_hr_2v2[2] if p1_hr_2v2 and len(p1_hr_2v2) > 2 else 0,
                         p1_hr_2v2[3] if p1_hr_2v2 and len(p1_hr_2v2) > 3 else 0)
            p2_hr2_wl = (p2_hr_2v2[2] if p2_hr_2v2 and len(p2_hr_2v2) > 2 else 0,
                         p2_hr_2v2[3] if p2_hr_2v2 and len(p2_hr_2v2) > 3 else 0)
            hr_items.append(("HR 2v2", str(p1_hr2), str(p2_hr2), bool(p1_hr_2v2), bool(p2_hr_2v2), p1_hr2_wl, p2_hr2_wl))
        elif queue_focus == "3v3":
            p1_hr3 = p1_hr_3v3[0] if p1_hr_3v3 else starting_elo
            p2_hr3 = p2_hr_3v3[0] if p2_hr_3v3 else starting_elo
            p1_hr3_wl = (p1_hr_3v3[2] if p1_hr_3v3 and len(p1_hr_3v3) > 2 else 0,
                         p1_hr_3v3[3] if p1_hr_3v3 and len(p1_hr_3v3) > 3 else 0)
            p2_hr3_wl = (p2_hr_3v3[2] if p2_hr_3v3 and len(p2_hr_3v3) > 2 else 0,
                         p2_hr_3v3[3] if p2_hr_3v3 and len(p2_hr_3v3) > 3 else 0)
            hr_items.append(("HR 3v3", str(p1_hr3), str(p2_hr3), bool(p1_hr_3v3), bool(p2_hr_3v3), p1_hr3_wl, p2_hr3_wl))

        if hr_items:
            hr_section_h = 60
            _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + hr_section_h),
                               radius=10, fill=CARD_BG)
            draw.text((PADDING + INNER_PAD, y_cursor + 6), "HIGH RANK", fill=TEXT_MUTED, font=font_label)

            hr_item_count = len(hr_items)
            hr_item_w = (CARD_WIDTH - 2 * PADDING) // hr_item_count
            for i, (hr_label, v1, v2, has1, has2, p1_wl, p2_wl) in enumerate(hr_items):
                cx = PADDING + i * hr_item_w + hr_item_w // 2

                if i > 0:
                    sep_x = PADDING + i * hr_item_w
                    draw.line([(sep_x, y_cursor + 14), (sep_x, y_cursor + hr_section_h - 10)],
                              fill=CARD_BORDER, width=1)

                l_bbox = draw.textbbox((0, 0), hr_label, font=font_label)
                l_w = l_bbox[2] - l_bbox[0]
                draw.text((cx - l_w // 2, y_cursor + 16), hr_label, fill=TEXT_MUTED, font=font_label)

                v1_bbox = draw.textbbox((0, 0), v1, font=font_large)
                v1_w = v1_bbox[2] - v1_bbox[0]
                draw.text((cx - v1_w - 6, y_cursor + 28), v1,
                          fill=p1_accent if has1 else TEXT_MUTED, font=font_large)
                draw.text((cx - 2, y_cursor + 28), "|", fill=TEXT_MUTED, font=font_small)
                draw.text((cx + 6, y_cursor + 28), v2,
                          fill=p2_accent if has2 else TEXT_MUTED, font=font_large)

                # W/L below ELO values
                wl_text = f"{p1_wl[0]}W {p1_wl[1]}L | {p2_wl[0]}W {p2_wl[1]}L"
                wl_bbox = draw.textbbox((0, 0), wl_text, font=font_label)
                wl_w = wl_bbox[2] - wl_bbox[0]
                draw.text((cx - wl_w // 2, y_cursor + 46), wl_text, fill=TEXT_GRAY, font=font_label)

            y_cursor += hr_section_h + 10

    # ════════════════════════════════════════════
    #  HIGH RANK CORE STATS (compare version)
    # ════════════════════════════════════════════
    hr_compare_rows = []
    if queue_focus == "regular":
        p1_hr_g = p1_hr[4] if p1_hr and len(p1_hr) > 4 else 0
        p1_hr_w_val = p1_hr[5] if p1_hr and len(p1_hr) > 5 else 0
        p1_hr_l_val = p1_hr[6] if p1_hr and len(p1_hr) > 6 else 0
        p2_hr_g = p2_hr[4] if p2_hr and len(p2_hr) > 4 else 0
        p2_hr_w_val = p2_hr[5] if p2_hr and len(p2_hr) > 5 else 0
        p2_hr_l_val = p2_hr[6] if p2_hr and len(p2_hr) > 6 else 0
        q1_wr = (p1_hr_w_val / p1_hr_g * 100) if p1_hr_g > 0 else 0
        q2_wr = (p2_hr_w_val / p2_hr_g * 100) if p2_hr_g > 0 else 0
        q1_ws = p1_streaks_hr[0] if p1_streaks_hr else 0
        q2_ws = p2_streaks_hr[0] if p2_streaks_hr else 0
        q1_ls = p1_streaks_hr[1] if p1_streaks_hr else 0
        q2_ls = p2_streaks_hr[1] if p2_streaks_hr else 0
        q1_bws = p1_streaks_hr[2] if p1_streaks_hr else 0
        q2_bws = p2_streaks_hr[2] if p2_streaks_hr else 0
        q1_bls = p1_streaks_hr[3] if p1_streaks_hr else 0
        q2_bls = p2_streaks_hr[3] if p2_streaks_hr else 0
        hr_compare_rows.append(("HIGH RANK", q1_wr, q2_wr, p1_hr_w_val, p2_hr_w_val, p1_hr_l_val, p2_hr_l_val,
                                p1_hr_g, p2_hr_g, q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls))
    elif queue_focus == "2v2":
        p1_hr2_g = p1_hr_2v2[1] if p1_hr_2v2 else 0
        p1_hr2_w = p1_hr_2v2[2] if p1_hr_2v2 else 0
        p1_hr2_l = p1_hr_2v2[3] if p1_hr_2v2 else 0
        p2_hr2_g = p2_hr_2v2[1] if p2_hr_2v2 else 0
        p2_hr2_w = p2_hr_2v2[2] if p2_hr_2v2 else 0
        p2_hr2_l = p2_hr_2v2[3] if p2_hr_2v2 else 0
        q1_wr = (p1_hr2_w / p1_hr2_g * 100) if p1_hr2_g > 0 else 0
        q2_wr = (p2_hr2_w / p2_hr2_g * 100) if p2_hr2_g > 0 else 0
        q1_ws = p1_streaks_hr_2v2[0] if p1_streaks_hr_2v2 else 0
        q2_ws = p2_streaks_hr_2v2[0] if p2_streaks_hr_2v2 else 0
        q1_ls = p1_streaks_hr_2v2[1] if p1_streaks_hr_2v2 else 0
        q2_ls = p2_streaks_hr_2v2[1] if p2_streaks_hr_2v2 else 0
        q1_bws = p1_streaks_hr_2v2[2] if p1_streaks_hr_2v2 else 0
        q2_bws = p2_streaks_hr_2v2[2] if p2_streaks_hr_2v2 else 0
        q1_bls = p1_streaks_hr_2v2[3] if p1_streaks_hr_2v2 else 0
        q2_bls = p2_streaks_hr_2v2[3] if p2_streaks_hr_2v2 else 0
        hr_compare_rows.append(("HR 2V2", q1_wr, q2_wr, p1_hr2_w, p2_hr2_w, p1_hr2_l, p2_hr2_l,
                                p1_hr2_g, p2_hr2_g, q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls))
    elif queue_focus == "3v3":
        p1_hr3_g = p1_hr_3v3[1] if p1_hr_3v3 else 0
        p1_hr3_w = p1_hr_3v3[2] if p1_hr_3v3 else 0
        p1_hr3_l = p1_hr_3v3[3] if p1_hr_3v3 else 0
        p2_hr3_g = p2_hr_3v3[1] if p2_hr_3v3 else 0
        p2_hr3_w = p2_hr_3v3[2] if p2_hr_3v3 else 0
        p2_hr3_l = p2_hr_3v3[3] if p2_hr_3v3 else 0
        q1_wr = (p1_hr3_w / p1_hr3_g * 100) if p1_hr3_g > 0 else 0
        q2_wr = (p2_hr3_w / p2_hr3_g * 100) if p2_hr3_g > 0 else 0
        q1_ws = p1_streaks_hr_3v3[0] if p1_streaks_hr_3v3 else 0
        q2_ws = p2_streaks_hr_3v3[0] if p2_streaks_hr_3v3 else 0
        q1_ls = p1_streaks_hr_3v3[1] if p1_streaks_hr_3v3 else 0
        q2_ls = p2_streaks_hr_3v3[1] if p2_streaks_hr_3v3 else 0
        q1_bws = p1_streaks_hr_3v3[2] if p1_streaks_hr_3v3 else 0
        q2_bws = p2_streaks_hr_3v3[2] if p2_streaks_hr_3v3 else 0
        q1_bls = p1_streaks_hr_3v3[3] if p1_streaks_hr_3v3 else 0
        q2_bls = p2_streaks_hr_3v3[3] if p2_streaks_hr_3v3 else 0
        hr_compare_rows.append(("HR 3V3", q1_wr, q2_wr, p1_hr3_w, p2_hr3_w, p1_hr3_l, p2_hr3_l,
                                p1_hr3_g, p2_hr3_g, q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls))

    for qi, (q_label, q1_wr, q2_wr, q1_w, q2_w, q1_l, q2_l, q1_g, q2_g,
             q1_ws, q2_ws, q1_ls, q2_ls, q1_bws, q2_bws, q1_bls, q2_bls) in enumerate(hr_compare_rows):
        stats_h = 70
        _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + stats_h),
                           radius=10, fill=CARD_BG)

        draw.text((PADDING + INNER_PAD, y_cursor + 2), q_label, fill=p1_accent, font=font_label)

        stat_items = [
            ("WIN RATE", f"{q1_wr:.1f}%", f"{q2_wr:.1f}%",
             WIN_COLOR if q1_wr >= 50 else LOSS_COLOR, WIN_COLOR if q2_wr >= 50 else LOSS_COLOR),
            ("WINS", str(q1_w), str(q2_w), WIN_COLOR, WIN_COLOR),
            ("LOSSES", str(q1_l), str(q2_l), LOSS_COLOR, LOSS_COLOR),
            ("GAMES", str(q1_g), str(q2_g), TEXT_WHITE, TEXT_WHITE),
            ("W STREAK", str(q1_ws), str(q2_ws),
             WIN_COLOR if q1_ws > 0 else TEXT_MUTED, WIN_COLOR if q2_ws > 0 else TEXT_MUTED),
            ("L STREAK", str(q1_ls), str(q2_ls),
             LOSS_COLOR if q1_ls > 0 else TEXT_MUTED, LOSS_COLOR if q2_ls > 0 else TEXT_MUTED),
        ]

        stat_count = len(stat_items)
        stat_w = (CARD_WIDTH - 2 * PADDING) // stat_count

        for i, (label, v1, v2, c1, c2) in enumerate(stat_items):
            cx = PADDING + i * stat_w + stat_w // 2

            if i > 0:
                sep_x = PADDING + i * stat_w
                draw.line([(sep_x, y_cursor + 16), (sep_x, y_cursor + stats_h - 14)],
                          fill=CARD_BORDER, width=1)

            l_bbox = draw.textbbox((0, 0), label, font=font_label)
            l_w = l_bbox[2] - l_bbox[0]
            draw.text((cx - l_w // 2, y_cursor + 12), label, fill=TEXT_MUTED, font=font_label)

            v1_bbox = draw.textbbox((0, 0), v1, font=font_large)
            v1_w = v1_bbox[2] - v1_bbox[0]
            draw.text((cx - v1_w - 6, y_cursor + 28), v1, fill=c1, font=font_large)
            draw.text((cx - 2, y_cursor + 28), "|", fill=TEXT_MUTED, font=font_small)
            draw.text((cx + 6, y_cursor + 28), v2, fill=c2, font=font_large)

            if label == "W STREAK":
                sub = f"best: {q1_bws} | {q2_bws}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 50), sub, fill=TEXT_MUTED, font=font_label)
            elif label == "L STREAK":
                sub = f"best: {q1_bls} | {q2_bls}"
                s_bbox = draw.textbbox((0, 0), sub, font=font_label)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text((cx - s_w // 2, y_cursor + 50), sub, fill=TEXT_MUTED, font=font_label)

        y_cursor += stats_h + 10

    # ════════════════════════════════════════════
    #  RECENT GAMES (card-style boxes, split into two side-by-side panels)
    # ════════════════════════════════════════════
    p1_matches = p1_recent[:5] if p1_recent else []
    p2_matches = p2_recent[:5] if p2_recent else []

    recent_h = 78
    GAP_RECENT = 12
    half_recent_w = (CARD_WIDTH - 2 * PADDING - GAP_RECENT) // 2

    for side, (matches, p_accent, panel_label) in enumerate([
        (p1_matches, p1_accent, player1_name),
        (p2_matches, p2_accent, player2_name),
    ]):
        px = PADDING + side * (half_recent_w + GAP_RECENT)
        _draw_rounded_rect(draw, (px, y_cursor, px + half_recent_w, y_cursor + recent_h),
                           radius=10, fill=CARD_BG)
        draw.text((px + INNER_PAD, y_cursor + 6), "RECENT GAMES", fill=TEXT_MUTED, font=font_label)

        if matches:
            box_y = y_cursor + 22
            panel_content_w = half_recent_w - 2 * INNER_PAD
            num_matches = min(len(matches), 5)
            box_gap = 6
            box_w = (panel_content_w - (num_matches - 1) * box_gap) // num_matches
            box_h = 48

            for mi, match in enumerate(matches):
                match_id, is_win, elo_change, position = match
                bx = px + INNER_PAD + mi * (box_w + box_gap)

                badge_color = WIN_COLOR if is_win else LOSS_COLOR
                _draw_rounded_rect(draw, (bx, box_y, bx + box_w, box_y + box_h),
                                   radius=6, fill=_dim_color(badge_color, 0.15),
                                   outline=_dim_color(badge_color, 0.4), width=1)

                # Top: W/L + change
                badge_text = "W" if is_win else "L"
                change_text = f"+{elo_change}" if elo_change >= 0 else str(elo_change)
                top_text = f"{badge_text} {change_text}"
                top_bbox = draw.textbbox((0, 0), top_text, font=font_medium_bold)
                top_w = top_bbox[2] - top_bbox[0]
                draw.text((bx + (box_w - top_w) // 2, box_y + 6), top_text,
                          fill=badge_color, font=font_medium_bold)

                # Bottom: Position
                if position:
                    pos_abbrev = str(position)
                    pos_map = {
                        "Defense Specialist": "DS", "Front Spiker": "FS",
                        "Setter": "S", "Libero": "L",
                        "highrank": "HR", "highrank_2v2": "HR 2v2", "highrank_3v3": "HR 3v3",
                        "2v2": "2v2", "3v3": "3v3", "6v6": "6v6",
                        "player": queue_focus.upper() if queue_focus in ("2v2", "3v3") else "6v6",
                        "Player": queue_focus.upper() if queue_focus in ("2v2", "3v3") else "6v6",
                    }
                    pos_abbrev = pos_map.get(pos_abbrev, pos_abbrev)
                    pa_bbox = draw.textbbox((0, 0), pos_abbrev, font=font_small)
                    pa_w = pa_bbox[2] - pa_bbox[0]
                    draw.text((bx + (box_w - pa_w) // 2, box_y + 27), pos_abbrev,
                              fill=TEXT_GRAY, font=font_small)
        else:
            draw.text((px + INNER_PAD, y_cursor + 36), "No recent matches",
                      fill=TEXT_MUTED, font=font_small)

    y_cursor += recent_h + 10

    # ════════════════════════════════════════════
    #  RATING HISTORY GRAPHS — Split per player
    # ════════════════════════════════════════════
    graph_h_each = 180
    graph_section_h = graph_h_each + 28 + 6  # per-player graph card

    # Filter history by queue focus and derive per-position data
    if queue_focus in ("2v2", "3v3"):
        qt_filter = queue_focus
        hr_qt_filter = f"highrank_{queue_focus}"
        p1_graph_reg = [h for h in (p1_history or []) if h[1] == qt_filter]
        p2_graph_reg = [h for h in (p2_history or []) if h[1] == qt_filter]
        p1_graph_hr = [h for h in (p1_history or []) if h[1] == hr_qt_filter]
        p2_graph_hr = [h for h in (p2_history or []) if h[1] == hr_qt_filter]
        per_pos_data = [None, None]
    else:
        p1_graph_reg = p1_history_regular
        p2_graph_reg = p2_history_regular
        p1_graph_hr = p1_history_highrank
        p2_graph_hr = p2_history_highrank
        # Derive per-position history from regular + HR history for each player
        per_pos_data = []
        for p_reg_hist, p_hr_hist, p_5v5 in [
            (p1_graph_reg, p1_graph_hr, p1_is_5v5),
            (p2_graph_reg, p2_graph_hr, p2_is_5v5),
        ]:
            all_hist = p_reg_hist or []
            ds_h = [h for h in all_hist if h[2] == 'Defense Specialist']
            fs_h = [h for h in all_hist if h[2] == 'Front Spiker']
            s_h = [h for h in all_hist if h[2] == 'Setter']
            l_h = [h for h in all_hist if h[2] == 'Libero'] if not p_5v5 else None
            # Per-position HR history
            all_hr_hist = p_hr_hist or []
            hr_ds_h = [h for h in all_hr_hist if h[2] == 'Defense Specialist']
            hr_fs_h = [h for h in all_hr_hist if h[2] == 'Front Spiker']
            hr_s_h = [h for h in all_hr_hist if h[2] == 'Setter']
            hr_l_h = [h for h in all_hr_hist if h[2] == 'Libero'] if not p_5v5 else None
            has_any = any(h and len(h) >= 1 for h in [ds_h, fs_h, s_h, l_h] if h is not None)
            has_any_hr = any(h and len(h) >= 1 for h in [hr_ds_h, hr_fs_h, hr_s_h, hr_l_h] if h is not None)
            if has_any or has_any_hr:
                per_pos_data.append((ds_h, fs_h, s_h, l_h, hr_ds_h, hr_fs_h, hr_s_h, hr_l_h, True))
            else:
                per_pos_data.append(None)

    GAP_GRAPH = 12
    half_graph_w = (CARD_WIDTH - 2 * PADDING - GAP_GRAPH) // 2
    inner_graph_w = half_graph_w - 2 * INNER_PAD

    for side, (p_name, p_reg, p_hr, p_accent) in enumerate([
        (player1_name, p1_graph_reg, p1_graph_hr, p1_accent),
        (player2_name, p2_graph_reg, p2_graph_hr, p2_accent),
    ]):
        gx = PADDING + side * (half_graph_w + GAP_GRAPH)
        _draw_rounded_rect(draw, (gx, y_cursor, gx + half_graph_w, y_cursor + graph_section_h),
                           radius=10, fill=CARD_BG)
        draw.text((gx + INNER_PAD, y_cursor + 6), f"RATING HISTORY — {p_name[:20]}",
                  fill=TEXT_MUTED, font=font_label)

        pos_data = per_pos_data[side] if per_pos_data else None
        if pos_data:
            # Show per-position lines (solid) + per-position HR lines (dashed)
            ds_h, fs_h, s_h, l_h, hr_ds_h, hr_fs_h, hr_s_h, hr_l_h, _ = pos_data
            graph_img = _generate_rating_graph_multiline(
                width=inner_graph_w,
                height=graph_h_each,
                accent_color=p_accent,
                history_ds=ds_h,
                history_fs=fs_h,
                history_s=s_h,
                history_l=l_h,
                history_hr_ds=hr_ds_h,
                history_hr_fs=hr_fs_h,
                history_hr_s=hr_s_h,
                history_hr_l=hr_l_h,
            )
        elif p_reg or p_hr:
            graph_img = _generate_rating_graph_multiline(
                history_regular=p_reg,
                history_highrank=p_hr,
                width=inner_graph_w,
                height=graph_h_each,
                accent_color=p_accent,
            )
        else:
            graph_img = _generate_rating_graph(None, width=inner_graph_w, height=graph_h_each,
                                               color=p_accent)
        graph_img = graph_img.resize((inner_graph_w, graph_h_each))
        img.paste(graph_img, (gx + INNER_PAD, y_cursor + 28))

    y_cursor += graph_section_h + 10

    # Crop to actual height
    img = img.crop((0, 0, CARD_WIDTH, y_cursor + 4))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


async def generate_leaderboard_card(
    title: str,
    rows: Optional[List] = None,  # list of (rank, username, value_text, sub_text, streak_text, avatar_bytes)
    page: int = 0,
    total_pages: int = 1,
    subtitle: str = "",
    queue_label: str = "Regular",
) -> io.BytesIO:
    """Generate an image-based leaderboard card with profile pictures."""
    if rows is None:
        rows = []

    CARD_WIDTH = 1060
    ROW_HEIGHT = 52
    HEADER_H = 70
    FOOTER_H = 40
    ROWS_PER_PAGE = 10

    row_count = len(rows)
    card_height = HEADER_H + ROWS_PER_PAGE * ROW_HEIGHT + FOOTER_H + 40

    img = Image.new('RGB', (CARD_WIDTH, card_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title = _get_font(20, bold=True)
    font_medium_bold = _get_font(14, bold=True)
    font_medium = _get_font(13)
    font_small = _get_font(12)
    font_tiny = _get_font(10)
    font_rank = _get_font(16, bold=True)

    PADDING = 20
    INNER_PAD = 15
    AVATAR_SIZE = 32

    # ── Header ──
    _draw_rounded_rect(draw, (PADDING, PADDING, CARD_WIDTH - PADDING, PADDING + HEADER_H),
                       radius=12, fill=CARD_BG, outline=CARD_BORDER, width=1)

    draw.text((PADDING + INNER_PAD, PADDING + 10), title, fill=TEXT_WHITE, font=font_title)
    if subtitle:
        draw.text((PADDING + INNER_PAD, PADDING + 36), subtitle, fill=TEXT_MUTED, font=font_tiny)

    badge_text = queue_label
    badge_bbox = draw.textbbox((0, 0), badge_text, font=font_small)
    badge_w = badge_bbox[2] - badge_bbox[0]
    badge_x = CARD_WIDTH - PADDING - INNER_PAD - badge_w - 16
    _draw_rounded_rect(draw, (badge_x, PADDING + 12, badge_x + badge_w + 16, PADDING + 32),
                       radius=8, fill=ACCENT_BLUE)
    draw.text((badge_x + 8, PADDING + 14), badge_text, fill=TEXT_WHITE, font=font_small)

    page_text = f"Page {page + 1}/{total_pages}"
    page_bbox = draw.textbbox((0, 0), page_text, font=font_tiny)
    page_w = page_bbox[2] - page_bbox[0]
    draw.text((CARD_WIDTH - PADDING - INNER_PAD - page_w, PADDING + 48), page_text, fill=TEXT_MUTED, font=font_tiny)

    y_cursor = PADDING + HEADER_H + 8

    # ── Leaderboard Rows ──
    content_h = ROWS_PER_PAGE * ROW_HEIGHT + 16
    _draw_rounded_rect(draw, (PADDING, y_cursor, CARD_WIDTH - PADDING, y_cursor + content_h),
                       radius=12, fill=CARD_BG, outline=CARD_BORDER, width=1)

    if not rows:
        empty_text = "No players yet"
        et_bbox = draw.textbbox((0, 0), empty_text, font=_get_font(14))
        et_w = et_bbox[2] - et_bbox[0]
        draw.text((CARD_WIDTH // 2 - et_w // 2, y_cursor + content_h // 2 - 8), empty_text, fill=TEXT_MUTED, font=_get_font(14))
    else:
        medal_colors = {
            1: ACCENT_GOLD,
            2: (192, 192, 192),
            3: (205, 127, 50),
        }

        for i, row_data in enumerate(rows):
            # Support both old format (5-tuple) and new format (6-tuple with avatar)
            if len(row_data) >= 6:
                rank, username, value_text, sub_text, streak_text, avatar_bytes = row_data[:6]
            else:
                rank, username, value_text, sub_text, streak_text = row_data[:5]
                avatar_bytes = None

            ry = y_cursor + 8 + i * ROW_HEIGHT

            if i % 2 == 0:
                _draw_rounded_rect(draw, (PADDING + 8, ry, CARD_WIDTH - PADDING - 8, ry + ROW_HEIGHT - 4),
                                   radius=6, fill=CARD_LIGHTER)

            # Rank number / medal
            rank_color = medal_colors.get(rank, TEXT_WHITE)
            rank_text = f"#{rank}"
            draw.text((PADDING + INNER_PAD + 4, ry + 12), rank_text, fill=rank_color, font=font_rank)

            # Profile picture
            avatar_x = PADDING + INNER_PAD + 50
            avatar_y = ry + (ROW_HEIGHT - 4 - AVATAR_SIZE) // 2
            if avatar_bytes:
                try:
                    av_img = Image.open(io.BytesIO(avatar_bytes)).resize((AVATAR_SIZE, AVATAR_SIZE))
                    mask = Image.new('L', (AVATAR_SIZE, AVATAR_SIZE), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=255)
                    img.paste(av_img, (avatar_x, avatar_y), mask)
                except Exception:
                    draw.ellipse((avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE),
                                fill=CARD_LIGHTER, outline=CARD_BORDER, width=1)
            else:
                draw.ellipse((avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE),
                            fill=CARD_LIGHTER, outline=CARD_BORDER, width=1)

            # Username (offset for avatar)
            name_x = avatar_x + AVATAR_SIZE + 10
            draw.text((name_x, ry + 6), username, fill=TEXT_WHITE, font=font_medium_bold)

            # Sub text (under username)
            if sub_text:
                draw.text((name_x, ry + 24), sub_text, fill=TEXT_MUTED, font=font_tiny)

            # Value
            v_bbox = draw.textbbox((0, 0), value_text, font=font_medium_bold)
            v_w = v_bbox[2] - v_bbox[0]
            value_color = ACCENT_BLUE if rank <= 3 else TEXT_WHITE
            draw.text((CARD_WIDTH - PADDING - INNER_PAD - v_w - 4, ry + 6), value_text, fill=value_color, font=font_medium_bold)

            # Streak text
            if streak_text:
                s_bbox = draw.textbbox((0, 0), streak_text, font=font_tiny)
                s_w = s_bbox[2] - s_bbox[0]
                streak_color = ACCENT_GREEN if "W" in streak_text else ACCENT_RED if "L" in streak_text else TEXT_MUTED
                draw.text((CARD_WIDTH - PADDING - INNER_PAD - s_w - 4, ry + 24), streak_text, fill=streak_color, font=font_tiny)

    y_cursor += content_h + 8

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf
