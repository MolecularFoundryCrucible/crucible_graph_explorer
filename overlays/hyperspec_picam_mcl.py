"""
Overlay adapter for hyperspectral (Raman/PL) scans from the HiP microscope.

Reads ``measurement/hyperspec_picam_mcl`` (an MCL-piezo raster of PI-CAM
spectra) and reduces it to a summed-intensity band map. This adapter backs the
Mosaic Viewer's correlative-overlay harness (``views/datasets/mosaic_viewer.py``).

Grid orientation: ``spec_map[0]`` is already de-serpentined and indexed by
(v, h), so row j ↔ ``v_array[j]`` and col i ↔ ``h_array[i]``. The viewer maps
this local (col, row) grid onto the mosaic via click-pair registration.
"""

import numpy as np

from .base import OverlayAdapter

GROUP = 'measurement/hyperspec_picam_mcl'

# Spectral-axis dataset name -> display label. Whichever exist are offered.
X_AXES = {
    'wls':          'Wavelength (nm)',
    'wave_numbers': 'Wave numbers (cm⁻¹)',
    'raman_shifts': 'Raman shift (cm⁻¹)',
}


class HyperspecPicamMclAdapter(OverlayAdapter):
    MEASUREMENT_TYPES = ['hyperspec_picam_mcl']

    def _meas(self, h5):
        return h5[GROUP]

    def _spectral_axes(self, g):
        return {k: g[k][:].tolist() for k in X_AXES if k in g}

    def descriptor(self, h5) -> dict:
        g = self._meas(h5)
        h_array = g['h_array'][:]
        v_array = g['v_array'][:]
        Nh, Nv = len(h_array), len(v_array)
        dh = float(abs(h_array[1] - h_array[0])) if Nh > 1 else 1.0
        dv = float(abs(v_array[1] - v_array[0])) if Nv > 1 else 1.0
        # Prefer the stored imshow_extent (matplotlib [xmin,xmax,ymin,ymax]);
        # fall back to array min/max padded by half a pixel.
        if 'imshow_extent' in g:
            ext = [float(x) for x in g['imshow_extent'][:]]
        else:
            ext = [float(h_array.min()) - dh / 2, float(h_array.max()) + dh / 2,
                   float(v_array.min()) - dv / 2, float(v_array.max()) + dv / 2]
        axes = self._spectral_axes(g)
        return {
            'grid': {
                'Nh': Nh, 'Nv': Nv,
                'extent_local': ext,
                'pixel_size': dh, 'units': 'um',
                'h_array': h_array.tolist(), 'v_array': v_array.tolist(),
            },
            'reductions': [{
                'id': 'band_sum',
                'label': 'Band sum',
                'axes': list(axes.keys()),
                'axis_labels': {k: X_AXES[k] for k in axes},
                'params': {'spec_min': None, 'spec_max': None},
            }],
            'spectral_axis': axes,
            'stage_hint': None,   # MCL-piezo frame has no shared origin (see plan §0)
        }

    def reduce(self, h5, params: dict) -> dict:
        g = self._meas(h5)
        x_axis = params.get('x_axis') or 'wls'
        if x_axis not in g:
            x_axis = 'wls'
        spec_min = params.get('spec_min')
        spec_max = params.get('spec_max')
        h_array = g['h_array'][:]
        v_array = g['v_array'][:]
        x_vals = g[x_axis][:]
        if spec_min is not None or spec_max is not None:
            lo = spec_min if spec_min is not None else float(x_vals.min())
            hi = spec_max if spec_max is not None else float(x_vals.max())
            idxs = np.where((x_vals >= min(lo, hi)) & (x_vals <= max(lo, hi)))[0]
            if len(idxs):
                img = g['spec_map'][0, :, :, int(idxs[0]):int(idxs[-1]) + 1].sum(axis=2)
            else:
                img = np.zeros((len(v_array), len(h_array)))
        else:
            img = g['spec_map'][0, :, :, :].sum(axis=2)

        img = np.asarray(img, dtype=float)
        vmin, vmax = self._robust_range(img)
        return {
            'Nh': len(h_array), 'Nv': len(v_array),
            'map_data': img.tolist(),
            'vmin': vmin, 'vmax': vmax,
            'x_label': X_AXES.get(x_axis, X_AXES['wls']),
        }

    def probe(self, h5, xi: int, yi: int):
        g = self._meas(h5)
        sm = g['spec_map']
        Nv, Nh = int(sm.shape[1]), int(sm.shape[2])
        if not (0 <= xi < Nh and 0 <= yi < Nv):
            return None
        spec = np.asarray(sm[0, yi, xi, :], dtype=float)
        axes = self._spectral_axes(g)
        return {
            'xi': xi, 'yi': yi,
            'intensity': spec.tolist(),
            'spectral_axis': axes,
            'axis_labels': {k: X_AXES[k] for k in axes},
        }

    @staticmethod
    def _robust_range(img):
        """Suggested [vmin, vmax] from robust (1/99) percentiles of finite values."""
        finite = img[np.isfinite(img)]
        if not finite.size:
            return 0.0, 1.0
        vmin = float(np.percentile(finite, 1))
        vmax = float(np.percentile(finite, 99))
        if vmax <= vmin:
            vmin, vmax = float(finite.min()), float(finite.max())
        if vmax <= vmin:
            vmax = vmin + 1.0
        return vmin, vmax
