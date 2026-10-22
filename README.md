# ZMART Microscopy

[![python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![status](https://img.shields.io/badge/status-early%20alpha-red)

<img src="docs/zmart-microscopy-icon.png" align="left" width="240" alt="ZMART microscopy">

**ZMART** (ZMB's Microscopy-Agnostic Research Toolkit) is the set of tools we use for smart microscopy
at the Center for Microscopy and Image Analysis (ZMB), University of Zurich.
This repository puts them together.
<br clear="left"/>

## The tools

<table>
<tr>
<td width="46%" valign="middle">
<img src="docs/zmart-hexagon.png" width="100%" alt="The six ZMART building blocks around ZMART Microscopy: interface, AI agent, controller, drivers, analysis and viewer">
</td>
<td valign="middle">

<p><a href="https://github.com/ZMB-UZH/ZMART-drivers"><b>ZMART drivers</b></a><br>
One driver per microscope (Leica, Nikon, ZEISS, mesoSPIM), each translating the controller's commands into what that microscope understands</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-controller"><b>ZMART Controller</b></a><br>
A short list of plain commands (move, read the state, acquire) that works the same on every microscope with a driver</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-interface"><b>ZMART interface</b></a><br>
The operator window: scan an overview, find targets, image them again</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-analysis"><b>ZMART analysis</b></a><br>
The analysis engine that runs between acquisitions (focus, object detection), each step in its own environment</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-viewer"><b>ZMART viewer</b></a><br>
Shows a run as OME-Zarr while it is still being acquired</p>
<p><a href="https://github.com/thomdehoog/ZMART-ai-agent"><b>ZMART AI agent</b></a><br>
Drives a microscope when you ask in your own words</p>

</td>
</tr>
</table>

## Example workflows

- [For coders](workflows/for-coders/): a Jupyter notebook that drives the microscope with a few lines of Python.
- [For non-coders](workflows/for-non-coders/): the operator window, no code.

## Author
Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).

## License
MIT License. See LICENSE file for details.
