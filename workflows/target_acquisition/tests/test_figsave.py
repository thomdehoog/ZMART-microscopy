"""save_figure writes a PNG plus vector siblings (SVG + PDF).

Every figure-save site in the pipeline routes through save_figure, so
pinning the helper pins the behavior everywhere: the operator gets a
quick-look PNG and vector copies to open in Affinity / Illustrator.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pipeline._figsave import save_figure


def _toy_figure():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_title("toy")
    return fig


def test_writes_png_svg_and_pdf_siblings(tmp_path):
    fig = _toy_figure()
    try:
        save_figure(fig, tmp_path / "fig.png")
    finally:
        plt.close(fig)

    png = tmp_path / "fig.png"
    svg = tmp_path / "fig.svg"
    pdf = tmp_path / "fig.pdf"

    # All three siblings exist, share the stem, and carry real bytes.
    assert {p.name for p in tmp_path.iterdir()} == {"fig.png", "fig.svg", "fig.pdf"}
    assert png.stat().st_size > 0
    # SVG is real vector XML, PDF is a real PDF -- not empty placeholders.
    assert svg.read_text(encoding="utf-8").lstrip().startswith("<?xml")
    assert "<svg" in svg.read_text(encoding="utf-8")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_forwards_savefig_kwargs(tmp_path):
    """Extra kwargs (e.g. facecolor) reach every format without error."""
    fig = _toy_figure()
    try:
        save_figure(fig, tmp_path / "fig.png", facecolor="white")
    finally:
        plt.close(fig)

    for name in ("fig.png", "fig.svg", "fig.pdf"):
        assert (tmp_path / name).stat().st_size > 0
