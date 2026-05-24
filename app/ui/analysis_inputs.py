"""Phantom + field-strength + sequence input widgets shown at the top of
the Analysis tab.

The widget keys are suffixed with the loaded series UID so picking a
different series re-mounts the dropdowns with fresh detected defaults
via ``index=``. User overrides within the same series persist because
the key stays stable across reruns of that series. This avoids the
Streamlit quirk where pre-render assignment to
``st.session_state[widget_key]`` is not honored once the widget has
already been instantiated under that key in a prior run.
"""

from __future__ import annotations

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.phantom import detect_phantom_spec
from ..utils.phantom_spec import LARGE, PHANTOMS


def detect_sequence_type(tr_ms: float, te_ms: float) -> str:
    """Classify an ACR phantom acquisition as T1 or T2 from TR/TE.

    The ACR axial protocol nominates TR≈500 / TE≈20 for T1 and
    TR≈2000 / TE≈80 for T2, so TE alone is a clean separator. TR is
    used as a tiebreaker when TE is missing.
    """
    if te_ms and te_ms > 0:
        return "T2" if te_ms >= 40.0 else "T1"
    if tr_ms and tr_ms > 0:
        return "T2" if tr_ms >= 1000.0 else "T1"
    return "T1"


def render(
    series: DicomSeries,
    *,
    key_prefix: str,
    show_sequence: bool = True,
) -> None:
    """Render the phantom + field-strength (+ sequence, axial only) inputs
    and apply the user's choices to ``series`` in place. ``key_prefix``
    keeps the keys unique when the same controls render on more than one
    tab body within a single run.
    """
    series_uid = st.session_state.get("loaded_series_uid") or str(id(series))
    series_tag = "".join(c if c.isalnum() else "_" for c in str(series_uid))[-32:]

    idx0 = series.acr_slice_map.get(1, 0)
    spec_auto = detect_phantom_spec(
        series.pixel_array[idx0], series.metadata.pixel_spacing_mm,
    )
    detected_phantom = spec_auto.short_name
    b0 = series.metadata.field_strength_t
    detected_field = "3.0 T" if b0 >= 2.0 else "1.5 T"
    detected_sequence = detect_sequence_type(
        series.metadata.repetition_time_ms, series.metadata.echo_time_ms,
    )

    phantom_options_pairs = [(s.short_name, s.name) for s in PHANTOMS.values()]
    phantom_options = [opt[0] for opt in phantom_options_pairs]
    phantom_label = dict(phantom_options_pairs)
    field_options = ["1.5 T", "3.0 T"]
    sequence_options = ["T1", "T2"]

    cols = st.columns(3 if show_sequence else 2)
    with cols[0]:
        choice = st.selectbox(
            "ACR phantom model",
            options=phantom_options,
            format_func=lambda k: phantom_label[k],
            index=phantom_options.index(detected_phantom),
            key=f"{key_prefix}_phantom_{series_tag}",
            help="Pre-selected from the phantom's segmented left-right width. "
                 "Large = 190 mm Ø / 148 mm S-I; Medium = 165 mm Ø / 134 mm S-I.",
        )
    with cols[1]:
        fld = st.selectbox(
            "Scanner field strength",
            options=field_options,
            index=field_options.index(detected_field),
            key=f"{key_prefix}_field_{series_tag}",
            help="Pre-selected from the DICOM MagneticFieldStrength tag "
                 "(snapped to the nearest of 1.5 / 3.0 T).",
        )
    if show_sequence:
        with cols[2]:
            seq = st.selectbox(
                "Axial sequence",
                options=sequence_options,
                index=sequence_options.index(detected_sequence),
                key=f"{key_prefix}_sequence_{series_tag}",
                help="Pre-selected from TR / TE (T2 when TE ≥ 40 ms). At 1.5 T "
                     "the ACR LCD threshold is sequence-dependent: 30 spokes "
                     "for T1, 25 for T2.",
            )
        series.metadata.sequence = seq

    series.spec = PHANTOMS.get(choice, LARGE)
    series.metadata.field_strength_t = 1.5 if fld == "1.5 T" else 3.0
