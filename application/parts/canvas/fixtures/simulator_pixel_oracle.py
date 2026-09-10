import json
import sys
from pathlib import Path

import numpy as np
import zarr

records = json.loads(Path(sys.argv[1]).read_text())
cases = []
for record in (records[1], records[2]):
    group = zarr.open_group(record['zarr'], mode='r')
    values = np.asarray(group['0'])[0, 0]
    dataset = group.attrs['ome']['multiscales'][0]['datasets'][0]
    scale = next(t['scale'] for t in dataset['coordinateTransformations'] if t['type'] == 'scale')
    origin = next(t['translation'] for t in dataset['coordinateTransformations'] if t['type'] == 'translation')
    for mode in ('top', 'slice', 'max'):
        for plane in ((0, len(values)//2, len(values)-1) if mode != 'max' else (0,)):
            selected = values.max(axis=0) if mode == 'max' else values[plane]
            # Interior constant patches avoid raster edge/interpolation ambiguity.
            samples = []
            for y in range(4, 508, 7):
                for x in range(4, 508, 7):
                    value = int(selected[y, x])
                    if np.all(selected[y-2:y+3, x-2:x+3] == value):
                        samples.append([x, y, value])
            black = [p for p in samples if p[2] == 0][:15]
            signal = [p for p in samples if p[2] > 0][:30]
            assert signal, (record['job'], mode, plane)
            cases.append({'name':record['acquisition_type'], 'mode':mode, 'plane':plane,
                          'z':origin[2]+plane*scale[2], 'spacing':scale[4],
                          'centre':{'x':origin[4]+256*scale[4], 'y':origin[3]+256*scale[3]},
                          'samples':black+signal})
print(json.dumps(cases))
