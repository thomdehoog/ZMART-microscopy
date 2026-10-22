# ZMART Microscopy

[![python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![status](https://img.shields.io/badge/status-early%20alpha-red)

<table>
<tr>
<td width="30%" valign="middle">
<img src="docs/zmart-microscopy-icon.png" width="100%" alt="ZMART microscopy">
</td>
<td valign="middle">

**ZMART** (ZMB's Microscopy-Agnostic Research Toolkit) is the set of tools we use for smart microscopy
at the Center for Microscopy and Image Analysis (ZMB), University of Zurich.
This repository contains example workflows that you can implement on our microscopes.
It also contains an overview of the individual tools of the ZMART toolkit.

</td>
</tr>
</table>
<br>

## Example workflows

### For non-coders

- [Target acquisition workflow for non-coders](workflows/target_acquisition/for-non-coders/) using an intuitive interface
  <br>![supported: Leica STELLARIS](https://img.shields.io/badge/supported-Leica%20STELLARIS-blue)

### For coders

- [Target acquisition workflow for coders](workflows/target_acquisition/for-coders/) using a Jupyter notebook
  <br>![supported: Leica STELLARIS](https://img.shields.io/badge/supported-Leica%20STELLARIS-blue)

<br>

## Build your own workflow using the tools of ZMART

Each tool has its own repository and can be used on its own.

<table>
<tr>
<td width="46%" valign="middle">
<img src="docs/zmart-iceberg.png" width="100%" alt="The ZMART toolkit: the interface above the water, for non-coders; viewer, controller, analysis and drivers below, for coders">
</td>
<td valign="middle">

<p><a href="https://github.com/ZMB-UZH/ZMART-interface"><b>ZMART interface</b></a><br>
Provides the framework for creating intuitive user interfaces, so workflows can be simulated and optimized in a straightforward way for non-coders</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-viewer"><b>ZMART viewer</b></a><br>
Allows you to view all the data of your entire experiment in the space of your canvas</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-analysis"><b>ZMART analysis</b></a><br>
Allows you to generate image analysis pipelines that are optimized for live feedback on local computers, that are documented, reproducible and that you can share</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-controller"><b>ZMART Controller</b></a><br>
Distills talking to the microscope down to a uniform language, so the workflows you build with it become interoperable</p>
<p><a href="https://github.com/ZMB-UZH/ZMART-drivers"><b>ZMART drivers</b></a><br>
Provides an abstraction to interact with the microscope in a reproducible, robust and straightforward way</p>

</td>
</tr>
</table>
<br>

## Author
Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).

<br>

## License
MIT License. See LICENSE file for details.
