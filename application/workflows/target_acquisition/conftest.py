"""Which of this workflow's editions can be collected here.

The React widgets and the browser edition that embeds them both need
`anywidget`, which the repository does not require. Their packages import it as
they load — with a sentence telling an operator how to install it — so pytest
cannot be told to skip from inside a test module: by then the package has
already been imported and raised. It is told here instead, before it walks in.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

collect_ignore: list[str] = []

try:  # pragma: no cover - depends on what is installed, not on what runs
    import anywidget  # noqa: F401
except ImportError:
    collect_ignore += ["react", "webapp"]
