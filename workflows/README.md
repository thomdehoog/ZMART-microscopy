# Workflows

This is where ZMART workflows are composed from the blocks: a workflow says
what to image and what to do with the pictures, and leaves the rest to the
blocks it uses. It drives the microscope through the
[ZMART Controller](https://github.com/thomdehoog/ZMART-controller), so it runs on
any microscope with a [driver](https://github.com/thomdehoog/ZMART-drivers);
it hands pictures to [ZMART analysis](https://github.com/thomdehoog/ZMART-analysis)
and shows them with the [ZMART viewer](https://github.com/thomdehoog/ZMART-viewer).
Everything it needs is installed by [`install.py`](../install.py).

The first to be ported here are the target-acquisition notebooks: scan an
overview, find the cells or structures of interest, and image each of them
again at higher magnification. They were written against the copies of the
controller and drivers that used to live in this repository, and are kept in
its git history and in the archive branch until they are rewritten on the
installed blocks.

The same steps can already be run in the operator window of the
[ZMART interface](https://github.com/thomdehoog/ZMART-interface), without
writing any code.
