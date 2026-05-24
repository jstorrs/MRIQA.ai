"""Load an MRI ACR phantom DICOM series.

Responsibilities
----------------
1.  Take a list of DICOM file paths (or bytes from a Streamlit upload).
2.  Parse them with pydicom, drop non-image files, sort by `InstanceNumber`
    (fallback: `SliceLocation`).
3.  Stack pixel arrays into a (n_slices, rows, cols) numpy array.
4.  Pull out the metadata needed by the QA tests and the report header.
5.  Provide automatic mapping of physical slice indices to ACR slice
    *roles* (slice 1, 5, 7, 11). The mapping defaults to the natural
    order; the UI can override this.
"""

from __future__ import annotations

import logging
import struct
from io import BytesIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pydicom
from pydicom.dataset import FileDataset
from pydicom.errors import BytesLengthException, InvalidDicomError

from ..utils.phantom_spec import PhantomSpec, default_phantom

logger = logging.getLogger(__name__)

# Exceptions pydicom and friends raise on a file that isn't a usable DICOM.
# Anything outside this set is unexpected and should propagate so it's not
# silently swallowed. ValueError covers most malformed-tag conditions;
# BytesLengthException is pydicom's specific signal for a tag whose length
# doesn't divide its VR (often fires on PDFs/JPEGs read with force=True).
NOT_A_DICOM_ERRORS: tuple[type[Exception], ...] = (
    InvalidDicomError, BytesLengthException, OSError, struct.error,
    EOFError, ValueError,
)


@dataclass
class SeriesMetadata:
    patient_name: str = ""
    patient_id: str = ""
    study_date: str = ""
    manufacturer: str = ""
    model: str = ""
    field_strength_t: float = 0.0
    series_description: str = ""
    series_number: int = 0
    sequence: str = ""           # T1 / T2 / etc., best-effort from description
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0)  # (row, col)
    slice_thickness_mm: float = 0.0
    spacing_between_slices_mm: float = 0.0
    rows: int = 0
    cols: int = 0
    n_slices: int = 0
    repetition_time_ms: float = 0.0
    echo_time_ms: float = 0.0
    # When a multi-echo (e.g. double-echo T2) acquisition is uploaded, the
    # loader keeps only the longest-TE images per ACR Test Guidance § 0.3
    # ("only the second-echo images are evaluated"). The discarded TE values
    # are recorded here so validate_series can warn the user about the split.
    discarded_echo_times_ms: list[float] = field(default_factory=list)


@dataclass
class DicomSeries:
    pixel_array: np.ndarray            # shape (n_slices, rows, cols), float32
    slice_locations_mm: list[float]
    instance_numbers: list[int]
    metadata: SeriesMetadata
    datasets: list[FileDataset] = field(default_factory=list, repr=False)
    # Mapping from "ACR slice role" (e.g. 1, 5, 7, 11) -> physical slice index 0..n-1
    acr_slice_map: dict[int, int] = field(default_factory=dict)
    # Phantom model (Large, Medium, …) — every QA test reads spec from here so
    # geometry/threshold constants are not hardcoded per test.
    spec: PhantomSpec = field(default_factory=default_phantom)

    def slice(self, acr_role: int) -> np.ndarray:
        """Return the 2D pixel array for the given ACR slice role (1-based)."""
        if acr_role not in self.acr_slice_map:
            raise KeyError(f"No physical slice mapped to ACR slice {acr_role}")
        return self.pixel_array[self.acr_slice_map[acr_role]]

    def try_slice(
        self, acr_role: int, *, spec_fallback: bool = False,
    ) -> np.ndarray | None:
        """Return the 2D pixel array for ``acr_role``, or ``None`` if not
        available. With ``spec_fallback=True``, fall back to the spec's
        default role→index mapping (and cache the result in
        ``acr_slice_map``) when the role is missing from the live map.
        """
        if acr_role in self.acr_slice_map:
            return self.pixel_array[self.acr_slice_map[acr_role]]
        if spec_fallback:
            idx = self.spec.slice_role_indices.get(acr_role)
            if idx is not None and idx < self.pixel_array.shape[0]:
                self.acr_slice_map[acr_role] = idx
                return self.pixel_array[idx]
        return None


def _read_one(source) -> FileDataset | None:
    """Read a single DICOM from path, Path, bytes, or file-like.

    Returns None for anything that doesn't parse as a DICOM. Truly
    unexpected errors (programming bugs in pydicom, etc.) propagate so
    they aren't silently lost.
    """
    try:
        if hasattr(source, "read"):
            return pydicom.dcmread(source, force=True)
        if isinstance(source, (bytes, bytearray)):
            return pydicom.dcmread(BytesIO(source), force=True)
        return pydicom.dcmread(str(source), force=True)
    except NOT_A_DICOM_ERRORS:
        logger.debug("DICOM read failed for %r", source, exc_info=True)
        return None


def _has_image(ds: FileDataset) -> bool:
    try:
        _ = ds.pixel_array
        return True
    except (AttributeError, ValueError, KeyError):
        logger.debug("pixel_array unavailable for %r", ds, exc_info=True)
        return False


class DicomLoadError(ValueError):
    """User-facing DICOM load error.

    The `tip` field is a short remediation hint that the UI surfaces to
    pilots so they can fix the upload without needing to understand the
    technical detail.
    """

    def __init__(self, message: str, *, tip: str = ""):
        super().__init__(message)
        self.tip = tip


def _str_tag(ds: FileDataset, tag: str) -> str:
    return str(getattr(ds, tag, "") or "")


def _float_tag(ds: FileDataset, tag: str) -> float:
    return float(getattr(ds, tag, 0.0) or 0.0)


def _int_tag(ds: FileDataset, tag: str) -> int:
    return int(getattr(ds, tag, 0) or 0)


def _guess_sequence(description: str) -> str:
    desc = description.lower()
    if "t1" in desc:
        return "T1"
    if "t2" in desc or "dual" in desc:
        return "T2"
    if "loc" in desc:
        return "Localizer"
    return "Unknown"


def _metadata_from_dataset(
    head: FileDataset,
    volume: np.ndarray,
    discarded_echo_times: list[float],
) -> SeriesMetadata:
    """Extract a SeriesMetadata from the first dataset of the series."""
    ps = getattr(head, "PixelSpacing", [1.0, 1.0])
    description = _str_tag(head, "SeriesDescription")
    meta = SeriesMetadata(
        patient_name=_str_tag(head, "PatientName"),
        patient_id=_str_tag(head, "PatientID"),
        study_date=_str_tag(head, "StudyDate"),
        manufacturer=_str_tag(head, "Manufacturer"),
        model=_str_tag(head, "ManufacturerModelName"),
        field_strength_t=_float_tag(head, "MagneticFieldStrength"),
        series_description=description,
        series_number=_int_tag(head, "SeriesNumber"),
        sequence=_guess_sequence(description),
        pixel_spacing_mm=(float(ps[0]), float(ps[1])),
        slice_thickness_mm=_float_tag(head, "SliceThickness"),
        spacing_between_slices_mm=_float_tag(head, "SpacingBetweenSlices"),
        rows=int(volume.shape[1]),
        cols=int(volume.shape[2]),
        n_slices=int(volume.shape[0]),
        repetition_time_ms=_float_tag(head, "RepetitionTime"),
        echo_time_ms=_float_tag(head, "EchoTime"),
        discarded_echo_times_ms=list(discarded_echo_times),
    )
    return meta


def _pad_or_crop(arr: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Make sure all slices share the same (rows, cols)."""
    out = np.zeros(target_shape, dtype=arr.dtype)
    rs = min(arr.shape[0], target_shape[0])
    cs = min(arr.shape[1], target_shape[1])
    out[:rs, :cs] = arr[:rs, :cs]
    return out


def load_series(sources: Iterable) -> DicomSeries:
    """Load a list of DICOM sources into a sorted DicomSeries.

    `sources` may be paths, bytes, or file-like objects (Streamlit upload).
    Raises ``DicomLoadError`` with a human-readable ``tip`` on any failure.
    """
    if not sources:
        raise DicomLoadError(
            "No files received.",
            tip="Drag a folder zip or individual .dcm files into the uploader.",
        )

    datasets: list[FileDataset] = []
    n_inputs = 0
    n_unreadable = 0
    n_no_image = 0
    for s in sources:
        n_inputs += 1
        ds = _read_one(s)
        if ds is None:
            n_unreadable += 1
            continue
        if not _has_image(ds):
            n_no_image += 1
            continue
        datasets.append(ds)

    if not datasets:
        if n_inputs == 0:
            raise DicomLoadError(
                "No files received.",
                tip="Drag at least one .dcm file or a folder zip into the uploader.",
            )
        if n_unreadable == n_inputs:
            raise DicomLoadError(
                f"None of the {n_inputs} uploaded file(s) could be parsed as DICOM.",
                tip="Make sure you uploaded MR DICOMs (the .dcm files from the scanner, "
                    "or the folder zipped). PDFs, JPEGs, and PNGs are not DICOM.",
            )
        raise DicomLoadError(
            f"The uploaded file(s) parsed as DICOM but contain no image data "
            f"({n_no_image} of {n_inputs} were image-less).",
            tip="Likely a DICOMDIR, structured report, or non-image SOP class. "
                "Re-export the MR image series from your scanner, not the study folder.",
        )

    # Sanity: must look like an MR series
    head0 = datasets[0]
    modality = str(getattr(head0, "Modality", "") or "").upper()
    if modality and modality not in {"MR", "MRI"}:
        raise DicomLoadError(
            f"The uploaded series has Modality='{modality}', not MR.",
            tip="This tool is for MRI ACR phantom QA only. Upload an MR series.",
        )

    # Multi-echo split. The ACR T2 series may be acquired as a double-echo
    # spin echo (TE 20/80) on legacy protocols, in which case the upload will
    # contain two instances per slice. Per the 2022 ACR Large and Medium
    # Phantom Test Guidance § 0.3, "When analyzing data from a double-echo
    # acquisition, only the second-echo images (TE=80) are evaluated." We
    # generalize: when multiple distinct EchoTime values are present, keep
    # only the longest-TE group and record the discarded TEs for the UI.
    echo_groups: dict[float, list[FileDataset]] = {}
    for ds in datasets:
        te = round(float(getattr(ds, "EchoTime", 0.0) or 0.0), 1)
        echo_groups.setdefault(te, []).append(ds)

    discarded_echo_times: list[float] = []
    if len(echo_groups) > 1:
        kept_te = max(echo_groups)
        discarded_echo_times = sorted(te for te in echo_groups if te != kept_te)
        datasets = echo_groups[kept_te]

    # Sort: prefer InstanceNumber; fallback to SliceLocation (descending so
    # superior slices come first, then we reverse if needed).
    def sort_key(ds):
        inst = getattr(ds, "InstanceNumber", None)
        if inst is not None:
            return (0, int(inst))
        sl = getattr(ds, "SliceLocation", None)
        if sl is not None:
            return (1, float(sl))
        return (2, 0)

    datasets.sort(key=sort_key)

    # Stack arrays
    arrays = [ds.pixel_array.astype(np.float32) for ds in datasets]

    # Apply rescale slope/intercept if present
    arrays = [
        (a * float(getattr(ds, "RescaleSlope", 1.0))) + float(getattr(ds, "RescaleIntercept", 0.0))
        for a, ds in zip(arrays, datasets)
    ]

    # Confirm shape uniformity
    shape = arrays[0].shape
    arrays = [a if a.shape == shape else _pad_or_crop(a, shape) for a in arrays]
    volume = np.stack(arrays, axis=0)

    meta = _metadata_from_dataset(datasets[0], volume, discarded_echo_times)

    slice_locations = [float(getattr(ds, "SliceLocation", i)) for i, ds in enumerate(datasets)]
    instance_numbers = [int(getattr(ds, "InstanceNumber", i + 1)) for i, ds in enumerate(datasets)]

    spec = default_phantom()
    series = DicomSeries(
        pixel_array=volume,
        slice_locations_mm=slice_locations,
        instance_numbers=instance_numbers,
        metadata=meta,
        datasets=datasets,
        spec=spec,
    )
    series.acr_slice_map = default_acr_slice_map(volume.shape[0], spec)
    return series


def default_acr_slice_map(n_slices: int, spec: PhantomSpec | None = None) -> dict[int, int]:
    """The standard ACR axial protocol acquires 11 slices. The ACR test
    procedures reference *slice 1* (inferior, with the bars/wedges),
    *slice 5* (central), *slice 7* (uniform region), and *slice 11* (the
    superior wedge-pair). When a series matches the protocol slice count
    we use the spec's standard mapping. For shorter series we fall back
    to evenly-spaced picks so the app remains usable on partial data."""
    if spec is None:
        spec = default_phantom()
    if n_slices >= spec.n_protocol_slices:
        return dict(spec.slice_role_indices)
    if n_slices == 0:
        return {}
    # Best effort: spread across whatever we have
    n_prot = spec.n_protocol_slices
    out: dict[int, int] = {
        1: 0,
        5: min(n_slices - 1, n_slices // 2 - 1 if n_slices >= 2 else 0),
        7: min(n_slices - 1, (n_slices * 6) // n_prot),
        11: n_slices - 1,
    }
    # Map LCD-adjacent roles relative to whatever we picked for slice 11,
    # so LCD scoring still has something to display on partial series.
    last = out[11]
    for role, offset in ((10, 1), (9, 2), (8, 3)):
        idx = last - offset
        if idx >= 0:
            out[role] = idx
    return out


def load_series_from_folder(folder: str | Path) -> DicomSeries:
    folder = Path(folder)
    if not folder.exists():
        raise DicomLoadError(
            f"Folder not found: {folder}",
            tip="Check the path spelling.",
        )
    files = sorted([p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")])
    return load_series(files)


def validate_series(series: DicomSeries) -> list[str]:
    """Return a list of non-fatal warnings about an already-loaded series.

    These don't block analysis but surface to the user so they understand
    why a result may be suspect — e.g. wrong slice count, mixed series,
    non-axial orientation.
    """
    warnings: list[str] = []
    md = series.metadata
    spec = series.spec
    n_prot = spec.n_protocol_slices

    # Slice count
    if md.n_slices < 5:
        warnings.append(
            f"Series has only {md.n_slices} slice(s). The {spec.name} "
            f"protocol acquires {n_prot} axial slices. Tests that need slice "
            f"{n_prot} will fail."
        )
    elif md.n_slices < n_prot:
        warnings.append(
            f"Series has {md.n_slices} slices but the {spec.name} protocol "
            f"uses {n_prot}. Slice-role mapping has been guessed; verify on the "
            "Slice Mapping tab."
        )
    elif md.n_slices > n_prot:
        warnings.append(
            f"Series has {md.n_slices} slices (expected {n_prot}). Auto-mapping "
            f"picked the first {n_prot}; if your protocol differs, override on "
            "the Slice Mapping tab."
        )

    # Pixel spacing
    if md.pixel_spacing_mm[0] <= 0 or md.pixel_spacing_mm[1] <= 0:
        warnings.append(
            "PixelSpacing is missing or invalid in the DICOM metadata. "
            "All physical-distance measurements will be wrong."
        )
    elif md.pixel_spacing_mm[0] > 2.0 or md.pixel_spacing_mm[1] > 2.0:
        warnings.append(
            f"PixelSpacing {md.pixel_spacing_mm[0]:.2f}×{md.pixel_spacing_mm[1]:.2f} mm "
            "is unusually coarse for an ACR phantom acquisition (typical: ~0.98 mm)."
        )

    # Slice thickness
    if md.slice_thickness_mm <= 0:
        warnings.append(
            "SliceThickness is missing from the DICOM metadata."
        )
    elif md.slice_thickness_mm < 3 or md.slice_thickness_mm > 8:
        warnings.append(
            f"SliceThickness {md.slice_thickness_mm:.1f} mm differs from the "
            f"{spec.name} standard ({spec.nominal_slice_thickness_mm:.0f} mm)."
        )

    # Sequence guess
    if md.sequence == "Unknown":
        warnings.append(
            f"Could not identify sequence from SeriesDescription "
            f"('{md.series_description}'). Tests assume an ACR T1 or T2 axial series."
        )

    # Multi-echo series: warn the user what was kept/dropped.
    if md.discarded_echo_times_ms:
        kept = md.echo_time_ms
        dropped_str = ", ".join(f"{te:g} ms" for te in md.discarded_echo_times_ms)
        warnings.append(
            "Detected a multi-echo acquisition. Per the 2022 ACR Test Guidance "
            f"(§ 0.3), only the longest-TE images are evaluated — kept "
            f"TE = {kept:g} ms, dropped TE = {dropped_str}. If this looks wrong, "
            "re-export only the desired echo series from the scanner."
        )

    # Image orientation: the ACR axial protocol is, well, axial.
    ds = series.datasets[0] if series.datasets else None
    if ds is not None and hasattr(ds, "ImageOrientationPatient"):
        try:
            iop = [float(v) for v in ds.ImageOrientationPatient]
            # Axial: row direction ~[1,0,0], col direction ~[0,1,0]
            if not (abs(iop[0]) > 0.95 and abs(iop[4]) > 0.95):
                warnings.append(
                    "ImageOrientationPatient suggests the series is not strictly "
                    f"axial. {spec.name} procedures assume axial acquisition."
                )
        except (TypeError, ValueError, IndexError):
            pass

    return warnings
