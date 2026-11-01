"""Reaching ZMART-analysis: where its workflows are, one engine kept warm, and each step's adapter.

``workflows.py`` finds the ZMART-analysis checkout and its pipelines;
``warm.py`` keeps one engine running for the whole session, so a press pays
for the workers' start only once. The rest turns the interface's own records
into what a pipeline takes and reads the answer back: ``focus_score.py``
scores a focus stack, ``detection.py`` finds the objects in a field, and
``mask_view.py`` draws the masks detection wrote as pictures the page can
show. None of them talks to the instrument.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""
