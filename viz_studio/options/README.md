# Comparing three ways to draw the flat view

Three viewers, one interface, one measurement suite. `viz_studio/OPTIONS.md` says
why; `contract.md` beside this file says exactly what an option has to do;
`RESULTS.md` holds the numbers.

```
options/
  contract.md              the interface, restated beside the code — read this first
  RESULTS.md               the table, one column per option
  harness/                 the page that drives any option, and the shapes it draws
  neuroglancer-under/      option A: the engine underneath, the operator's drawing on top
  measure/                 the suite, run against each option in turn
  measurements/            what the last run produced: photographs and full readings
```

## Running it

Build the page once. It borrows the viewer's own installed packages rather than
keeping a second copy, so the engine being compared is the exact version the
viewer ships:

```
npm --prefix viz_studio/frontend install       # only if you have not already
npm --prefix viz_studio/options/harness run build
```

Then take the measurements:

```
python viz_studio/options/measure/run.py --option neuroglancer-under
python viz_studio/options/measure/run.py --option all
```

It writes photographs and a full set of readings into `measurements/`, and brings
the table in `RESULTS.md` up to date. It takes about two minutes per option on a
machine with no graphics card.

## Looking at it yourself

The harness is an ordinary page. Serve it and open it with a word in the address
to choose the option — **no rebuild between one option and the next**, which is
the whole point:

```
python - <<'EOF'
import sys; sys.path.insert(0, "viz_studio/options/measure")
from data_server import Ledger, make_measurement_server
from pathlib import Path
import acquisitions
data = Path("/tmp/zmart-options"); acquisitions.write_them_all(data)
server = make_measurement_server(
    port=8850, site_dir=Path("viz_studio/options/harness/dist"),
    data_dir=data, ledger=Ledger())
print("http://127.0.0.1:8850/?option=neuroglancer-under&draw=carrier&store=scattered")
server.serve_forever()
EOF
```

The words the address takes:

| | |
| --- | --- |
| `option=` | which of the three draws the picture |
| `store=` | `square`, `lopsided`, `sparse`, `scattered` or `fine` |
| `draw=carrier` | the operator's real drawing: a carrier outline and tile rectangles |
| `draw=margin` | the measuring instrument: a sheet with a hole cut around the picture |
| `draw=none` | nothing over the picture at all |
| `positions=` | how many tile rectangles the operator laid out |
| `bounded=0` | give the engine the whole window instead of only the imaged ground |
| `data=` | where the acquisitions are served from |

## The checks

`viz_studio/tests/test_the_options_hold_together.py` holds the promises every
option has to keep — micrometres, two gestures, addresses passed in, two viewers
on one page, the engine kept behind its adapter. Run them with a browser
required, so that a machine which could have drawn does:

```
ZMART_REQUIRE_BROWSER=1 python -m pytest viz_studio/tests/test_the_options_hold_together.py
```
