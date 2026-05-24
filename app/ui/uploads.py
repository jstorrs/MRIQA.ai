"""Sidebar uploader: catalog uploaded DICOMs, pick a series, surface load errors.

``render_sidebar()`` returns the local-folder string from the "load from a
local folder" expander (empty when not used). Everything else is wired
through session state: the series catalog lives in
``st.session_state.series_catalog`` and the currently picked entry in
``st.session_state.selected_series_uid``; the entry point reads those to
load a series. ``st.session_state.uploader_nonce`` is bumped on each
batch so the file_uploader widget re-mounts as a fresh empty drop zone.
"""

from __future__ import annotations

import io
import logging
import zipfile

import pydicom
import streamlit as st

from ..io_dicom.dicom_loader import DicomLoadError


logger = logging.getLogger(__name__)


def catalog_uploads(uploaded_files) -> list[dict]:
    """Group every DICOM file across the uploads by SeriesInstanceUID.

    Returns a list of entries like
        {"uid", "description", "number", "modality", "n_files", "sources"}
    sorted by SeriesNumber. Files without a parseable header are skipped
    silently; files without a SeriesInstanceUID are grouped under an empty
    UID so they can still be picked.
    """
    by_uid: dict[str, dict] = {}
    for uf in uploaded_files:
        name = uf.name.lower()
        data = uf.read()
        payloads: list[bytes] = []
        if name.endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    nlow = info.filename.lower()
                    if "__macosx" in nlow or nlow.endswith(".ds_store"):
                        continue
                    payloads.append(z.read(info))
            except zipfile.BadZipFile:
                st.error(f"Could not read zip: {uf.name}")
                continue
        else:
            payloads.append(data)
        for payload in payloads:
            try:
                ds = pydicom.dcmread(io.BytesIO(payload), force=True, stop_before_pixels=True)
            except Exception:
                logger.debug("Failed to read DICOM header from upload payload", exc_info=True)
                continue
            uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
            entry = by_uid.setdefault(uid, {
                "uid": uid,
                "description": str(getattr(ds, "SeriesDescription", "") or ""),
                "number": int(getattr(ds, "SeriesNumber", 0) or 0),
                "modality": str(getattr(ds, "Modality", "") or ""),
                "n_files": 0,
                "sources": [],
            })
            entry["n_files"] += 1
            entry["sources"].append(payload)
    return sorted(
        by_uid.values(),
        key=lambda e: (e["number"] or 0, e["description"]),
    )


def series_label(entry: dict) -> str:
    """One-line label for the series picker dropdown."""
    parts = []
    if entry["number"]:
        parts.append(f"#{entry['number']}")
    desc = entry["description"] or "(no description)"
    parts.append(desc)
    parts.append(f"[{entry['modality'] or '?'}, {entry['n_files']} files]")
    return " ".join(parts)


def show_load_error(exc: Exception) -> None:
    """Surface a DicomLoadError (or any other load failure) in the sidebar."""
    if isinstance(exc, DicomLoadError):
        st.sidebar.error(str(exc))
        if exc.tip:
            st.sidebar.info(f"**Tip:** {exc.tip}")
    else:
        st.sidebar.error(f"Failed to load DICOMs: {exc}")


def render_sidebar(app_version: str) -> str:
    """Render the sidebar uploader + series picker. Returns the contents of
    the "load from local folder" text input (empty when not used).

    Side effects: mutates ``st.session_state.series_catalog``,
    ``st.session_state.selected_series_uid``, and
    ``st.session_state.uploader_nonce`` so the entry point can pick up
    the user's choices on rerun.
    """
    with st.sidebar:
        st.header("Phantom DICOMs")
        st.markdown(
            "**Only upload ACR phantom scans.** Do not upload patient images. "
            "Free-tier deployments process files in memory; nothing is stored "
            "between sessions, but de-identify before uploading anyway."
        )
        st.markdown(
            "<div class='mri-small'>"
            "The app runs one of two analyses depending on the series you pick:"
            "<br>• <b>Axial series</b> — 11 axial slices (T1 or T2 ACR protocol)."
            "<br>• <b>Sagittal localizer</b> — single sagittal scout image."
            "<br><br>Phantom model + field-strength inputs live on the "
            "<b>Analysis</b> tab so the algorithm inputs sit together."
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        catalog = st.session_state.series_catalog
        if catalog:
            uid_options = [e["uid"] for e in catalog]
            labels = {e["uid"]: series_label(e) for e in catalog}
            if st.session_state.get("selected_series_uid") not in uid_options:
                st.session_state.selected_series_uid = uid_options[0]

            st.selectbox(
                f"Series ({len(catalog)} loaded)",
                options=uid_options,
                format_func=lambda u: labels[u],
                key="selected_series_uid",
                help="Pick which series to analyze. Drop more files below to "
                     "extend this list. Switch to the **Analysis** tab when "
                     "you pick a new series.",
            )

            if st.button("Clear all series", width="stretch"):
                for k in (
                    "series", "results", "series_warnings",
                    "view_wl", "view_ww",
                    "series_catalog", "selected_series_uid", "loaded_series_uid",
                ):
                    st.session_state.pop(k, None)
                st.rerun()

        new_uploads = st.file_uploader(
            "Add DICOMs (drop files or a .zip)",
            type=None,
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.uploader_nonce}",
            help="Drop .dcm files, a folder zip, or any mix. Each batch is "
                 "scanned and added to the series list above.",
        )

        if new_uploads:
            try:
                new_entries = catalog_uploads(new_uploads)
            except (zipfile.BadZipFile, OSError, DicomLoadError) as exc:
                show_load_error(exc)
                new_entries = []
            existing_uids = {e["uid"] for e in st.session_state.series_catalog}
            added = [e for e in new_entries if e["uid"] not in existing_uids]
            if added:
                st.session_state.series_catalog = (
                    st.session_state.series_catalog + added
                )
            elif new_entries:
                st.sidebar.info(
                    f"All {len(new_entries)} series in that batch are already "
                    "in the list."
                )
            elif not new_entries:
                show_load_error(DicomLoadError(
                    "No DICOM files found in the upload.",
                    tip="The uploader accepts .dcm files or zips containing them.",
                ))
            st.session_state.uploader_nonce += 1
            st.rerun()

        with st.expander("Advanced — load from a local folder"):
            local_folder = st.text_input(
                "Path to a folder of .dcm files",
                value="",
                help="Only works when running the app locally, not on Streamlit Cloud.",
            )

        st.divider()
        st.caption(f"App version {app_version}")

    return local_folder
