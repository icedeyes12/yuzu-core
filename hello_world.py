#!/usr/bin/env python3
"""
Yuzu Companion — Statistical Hello World
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import scipy.stats as stats
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def ascii_values(text: str) -> np.ndarray:
    """Convert text to ASCII values."""
    return np.array([ord(c) for c in text], dtype=np.int64)


def compute_svd(matrix: np.ndarray) -> dict:
    """Singular Value Decomposition."""
    U, s, Vt = np.linalg.svd(matrix, full_matrices=False)
    return {
        "U": U,
        "s": s,
        "Vt": Vt,
        "rank": np.linalg.matrix_rank(matrix),
        "condition": float(np.max(s) / np.min(s[s > 1e-10])),
    }


def compute_fft(signal: np.ndarray) -> dict:
    """Fast Fourier Transform analysis."""
    n = len(signal)
    fft_vals = np.fft.fft(signal)
    freqs = np.fft.fftfreq(n, d=1.0)
    magnitudes = np.abs(fft_vals)[: n // 2]
    dominant_idx = np.argmax(magnitudes)
    spectral_centroid = float(np.sum(freqs[: n // 2] * magnitudes) / np.sum(magnitudes))
    return {
        "fft_vals": fft_vals,
        "freqs": freqs,
        "dominant_freq": float(freqs[dominant_idx]),
        "dominant_magnitude": float(magnitudes[dominant_idx]),
        "spectral_centroid": spectral_centroid,
        "energy": float(np.sum(np.abs(fft_vals) ** 2)),
    }


def compute_stats(data: np.ndarray) -> dict:
    """Descriptive statistics."""
    n = len(data)
    mean_val = float(np.mean(data))
    std_val = float(np.std(data, ddof=1))
    median_val = float(np.median(data))
    q1, q3 = float(np.percentile(data, 25)), float(np.percentile(data, 75))
    iqr = q3 - q1
    t_crit = stats.t.ppf(0.975, df=n - 1)
    ci_low = mean_val - t_crit * std_val / math.sqrt(n)
    ci_high = mean_val + t_crit * std_val / math.sqrt(n)
    skew = float(stats.skew(data))
    kurt = float(stats.kurtosis(data))
    _, p_norm = stats.normaltest(data)
    is_normal = p_norm > 0.05
    return {
        "n": n,
        "mean": mean_val,
        "std": std_val,
        "min": float(np.min(data)),
        "max": float(np.max(data)),
        "median": median_val,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "skewness": skew,
        "kurtosis": kurt,
        "p_normaltest": p_norm,
        "is_normal": is_normal,
    }


GRADIENT_COLORS = ["blue", "cyan", "green", "yellow", "red"]


def get_gradient_color(value: float, min_val: float = 32, max_val: float = 114) -> str:
    """Get gradient color based on ASCII value range."""
    if max_val == min_val:
        ratio = 0.5
    else:
        ratio = (value - min_val) / (max_val - min_val)
    ratio = max(0.0, min(1.0, ratio))
    idx = int(ratio * (len(GRADIENT_COLORS) - 1))
    return GRADIENT_COLORS[idx]


def gradient_bar(value: float, max_val: float, width: int = 35) -> str:
    """Create a gradient-colored bar with Rich markup."""
    if max_val == 0:
        filled = 0
    else:
        filled = int((value / max_val) * width)
    empty = width - filled
    color = get_gradient_color(value)
    bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/dim]"
    return f"{bar} [white]{int(value):3d}[/white]"


def build_char_table(ascii_vals: np.ndarray, text: str) -> Table:
    """Build character analysis table."""
    table = Table(
        title="[bold magenta]Character Encoding[/bold magenta]",
        box=None,
        show_header=True,
        header_style="cyan",
    )
    table.add_column("Char", style="bold yellow", width=3, justify="center")
    table.add_column("ASCII", style="white", width=5, justify="right")
    table.add_column("Binary", style="dim", width=10)
    table.add_column("Hex", style="dim", width=5)
    table.add_column("#", style="dim", width=3, justify="right")
    for i, (char, val) in enumerate(zip(text, ascii_vals), 1):
        binary = format(val, "08b")
        hex_val = format(val, "02x").upper()
        char_display = char if char != " " else "␣"
        table.add_row(char_display, str(val), binary, f"0x{hex_val}", str(i))
    return table


def build_stats_table(desc: dict) -> Table:
    """Build descriptive statistics table."""
    table = Table(
        title="[bold magenta]Descriptive Statistics[/bold magenta]",
        box=None,
        show_header=False,
    )
    table.add_column("Metric", style="cyan", width=18)
    table.add_column("Value", style="white", justify="right")
    rows = [
        ("Count", f"{desc['n']}"),
        ("Mean", f"{desc['mean']:.2f}"),
        ("Std Dev", f"{desc['std']:.2f}"),
        ("Min", f"{desc['min']:.0f}"),
        ("Max", f"{desc['max']:.0f}"),
        ("Median", f"{desc['median']:.1f}"),
        ("IQR", f"{desc['iqr']:.1f}"),
        ("95% CI", f"[{desc['ci_low']:.2f}, {desc['ci_high']:.2f}]"),
    ]
    for metric, value in rows:
        table.add_row(metric, value)
    return table


def build_inference_table(desc: dict) -> Table:
    """Build inferential statistics table."""
    conclusion = "[green]Normal[/green]" if desc["is_normal"] else "[yellow]Non-normal[/yellow]"
    table = Table(
        title="[bold magenta]Inferential Statistics[/bold magenta]",
        box=None,
        show_header=False,
    )
    table.add_column("Metric", style="cyan", width=18)
    table.add_column("Value", style="white", justify="right")
    table.add_row("Skewness", f"{desc['skewness']:.4f}")
    table.add_row("Kurtosis", f"{desc['kurtosis']:.4f}")
    table.add_row("Normality Test", f"p = {desc['p_normaltest']:.4f}")
    table.add_row("Conclusion", conclusion)
    return table


def build_svd_table(svd_result: dict) -> Table:
    """Build SVD results table."""
    table = Table(
        title="[bold magenta]SVD — Singular Value Decomposition[/bold magenta]",
        box=None,
        show_header=False,
    )
    table.add_column("Metric", style="cyan", width=22)
    table.add_column("Value", style="white", justify="right")
    sv_str = ", ".join(f"{v:.2f}" for v in svd_result["s"])
    table.add_row("Matrix Shape", str(svd_result["s"].shape))
    table.add_row("Singular Values", sv_str)
    table.add_row("Matrix Rank", str(svd_result["rank"]))
    table.add_row("Condition Number", f"{svd_result['condition']:.2f}")
    return table


def build_fft_table(fft_result: dict) -> Table:
    """Build FFT results table."""
    table = Table(
        title="[bold magenta]FFT — Fast Fourier Transform[/bold magenta]",
        box=None,
        show_header=False,
    )
    table.add_column("Metric", style="cyan", width=22)
    table.add_column("Value", style="white", justify="right")
    table.add_row("Dominant Freq", f"{fft_result['dominant_freq']:.3f}Hz ({fft_result['dominant_magnitude']:.1f})")
    table.add_row("Spectral Centroid", f"{fft_result['spectral_centroid']:.3f} Hz")
    table.add_row("Signal Energy", f"{fft_result['energy']:.2f}")
    return table


def build_distribution_chart(ascii_vals: np.ndarray, text: str) -> Text:
    """Build colored distribution chart as single Text with markup."""
    max_val = float(np.max(ascii_vals))
    lines = []
    for i, (char, val) in enumerate(zip(text, ascii_vals), 1):
        char_display = char if char != " " else "␣"
        bar = gradient_bar(val, max_val, 35)
        lines.append(f"  [bold yellow]{char_display}[/bold yellow]  {bar}  [dim]#{i}[/dim]")
    return Text.from_markup("\n".join(lines))


def build_dramatic_reveal(text: str, ascii_vals: np.ndarray) -> Panel:
    """Build dramatic Hello World reveal."""
    chars = []
    for char, val in zip(text, ascii_vals):
        color = get_gradient_color(val)
        chars.append(f"[{color}]{char}[/{color}]")
    colored_text = "  ".join(chars)
    note = "Character-by-character coloring based on ASCII value intensity\nThis is what 'Hello World!' looks like as numbers"
    content = Text.from_markup(f"[bold]{colored_text}[/bold]\n\n[dim italic]{note}[/dim italic]")
    return Panel(
        content,
        title="[bold magenta]Dramatic Reveal[/bold magenta]",
        border_style="magenta",
        padding=(1, 2),
    )


def main() -> None:
    console = Console()
    text = "Hello World!"
    ascii_vals = ascii_values(text)
    matrix = ascii_vals.reshape(4, 3)
    svd_result = compute_svd(matrix)
    fft_result = compute_fft(ascii_vals.astype(float))
    desc = compute_stats(ascii_vals)

    header = Panel(
        Text.from_markup("[bold magenta]YUZU COMPANION[/bold magenta]"),
        title="Statistical Hello World",
        border_style="cyan",
        padding=(1, 1),
    )

    console.print(header)
    console.print()
    console.print(build_char_table(ascii_vals, text))
    console.print()
    console.print(build_stats_table(desc))
    console.print()
    console.print(build_inference_table(desc))
    console.print()
    console.print(build_svd_table(svd_result))
    console.print()
    console.print(build_fft_table(fft_result))
    console.print()

    dist_panel = Panel(
        build_distribution_chart(ascii_vals, text),
        title="[bold magenta]Distribution Pattern[/bold magenta]",
        border_style="cyan",
        padding=(1, 1),
    )
    console.print(dist_panel)
    console.print()
    console.print(build_dramatic_reveal(text, ascii_vals))
    console.print()

    note_panel = Panel(
        Text.from_markup("[dim italic]Note: p > 0.05 = Normal distribution (we accept H₀)[/dim italic]"),
        border_style="dim",
    )
    console.print(note_panel)
    console.print()

    footer = Panel(
        Text.from_markup(
            f"[cyan]Yuzu Companion v2.0[/cyan]  ·  numpy {np.__version__}  ·  scipy 1.17.1  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ),
        border_style="cyan",
    )
    console.print(footer)


if __name__ == "__main__":
    main()
