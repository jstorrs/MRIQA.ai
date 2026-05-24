import math
import unittest
from unittest.mock import patch

import numpy as np

from app.io_dicom.dicom_loader import DicomSeries, SeriesMetadata
from app.qa_tests import AXIAL_TEST_ORDER, applicable_test_order
from app.qa_tests import high_contrast_resolution, low_contrast_detectability
from app.qa_tests import slice_position, slice_thickness, uniformity
from app.utils.geometry import ellipse_axes_for_area_cm2
from app.utils.phantom import PhantomGeometry
from app.utils.phantom_spec import LARGE


def series_for(sequence="T1", field_strength=3.0, mapping=None):
    return DicomSeries(
        pixel_array=np.ones((11, 256, 256), dtype=np.float32),
        slice_locations_mm=list(range(11)),
        instance_numbers=list(range(1, 12)),
        metadata=SeriesMetadata(
            field_strength_t=field_strength,
            sequence=sequence,
            pixel_spacing_mm=(1.0, 1.0),
            n_slices=11,
        ),
        acr_slice_map=mapping or dict(LARGE.slice_role_indices),
        spec=LARGE,
    )


class ProtocolSpecificationTests(unittest.TestCase):
    def test_ghosting_air_roi_has_prescribed_area_and_aspect(self):
        long_axis, short_axis = ellipse_axes_for_area_cm2(10.0, 4.0)

        self.assertAlmostEqual(long_axis / short_axis, 4.0)
        self.assertAlmostEqual(math.pi * long_axis * short_axis / 4.0, 1000.0)

    def test_t2_excludes_t1_only_tests(self):
        t1_ids = {test.id for test in applicable_test_order(AXIAL_TEST_ORDER, "axial", "T1")}
        t2_ids = {test.id for test in applicable_test_order(AXIAL_TEST_ORDER, "axial", "T2")}

        self.assertIn("geometric_accuracy", t1_ids)
        self.assertIn("ghosting", t1_ids)
        self.assertNotIn("geometric_accuracy", t2_ids)
        self.assertNotIn("ghosting", t2_ids)

    def test_lcd_threshold_uses_all_field_bands_and_sequence(self):
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T1", 1.0), LARGE), 7)
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T1", 1.5), LARGE), 30)
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T2", 2.5), LARGE), 25)
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T2", 3.0), LARGE), 37)

    def test_lcd_threshold_treats_vendor_rounded_3t_as_high_field(self):
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T1", 2.95), LARGE), 37)
        self.assertEqual(low_contrast_detectability._threshold_for(series_for("T2", 2.89), LARGE), 25)

    def test_hcr_uses_fixed_spec_threshold_when_input_clean(self):
        series = series_for()
        geometry = PhantomGeometry(128.0, 128.0, 90.0, np.ones((256, 256), dtype=bool))
        with (
            patch.object(high_contrast_resolution, "localize_phantom", return_value=geometry),
            patch.object(
                high_contrast_resolution,
                "crop_resolution_insert",
                return_value=(np.ones((10, 10)), (0, 10, 0, 10)),
            ),
            patch.object(high_contrast_resolution, "_detect_resolution_grids", return_value=(None, None)),
            patch.object(high_contrast_resolution, "render_annotated", return_value=None),
        ):
            result = high_contrast_resolution.run(
                series,
                user_input={"UL": 1.1, "LR": 1.1},
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.measurements[0].spec, "≤ 1.0 mm")


class ResultSemanticsTests(unittest.TestCase):
    def test_large_piu_advisory_band_passes_with_warning(self):
        series = series_for(field_strength=1.5)
        series.pixel_array[:] = 100.0
        series.pixel_array[6, 120:137, 120:137] = 75.0
        geometry = PhantomGeometry(128.0, 128.0, 95.0, np.ones((256, 256), dtype=bool))
        with (
            patch.object(uniformity, "localize_phantom", return_value=geometry),
            patch.object(uniformity, "render_annotated", return_value=None),
        ):
            result = uniformity.run(series)

        self.assertTrue(result.passed)
        self.assertTrue(any("preferred" in warning for warning in result.warnings))

    def test_slice_position_cannot_pass_with_missing_required_slice(self):
        series = series_for(mapping={11: 10})
        measurement = slice_position._BarMeasurement(
            left_len=10.0,
            right_len=10.0,
            bar_diff=0.0,
            left_col=120,
            right_col=130,
            top=20.0,
            left_bot=30.0,
            right_bot=30.0,
            cx=128.0,
            radius_px=90.0,
            rim=10,
        )
        with (
            patch.object(slice_position, "_measure_one", return_value=measurement),
            patch.object(slice_position, "render_annotated", return_value=None),
        ):
            result = slice_position.run(series)

        self.assertEqual(result.status_text(), "ERROR")
        self.assertIn("Required ACR slice 1", result.error)

    def _ramp_fit(self, top_mm, bot_mm):
        ramp = slice_thickness.RampFit(fwhm_px=0.0, left_x=1.0, right_x=2.0)
        return slice_thickness.SliceThicknessFit(
            top_mm=top_mm, bot_mm=bot_mm, upper=ramp, lower=ramp,
        )

    def test_slice_thickness_advisory_band_passes_with_warning(self):
        series = series_for(mapping={1: 0})
        geometry = PhantomGeometry(128.0, 128.0, 90.0, np.ones((256, 256), dtype=bool))
        with (
            patch.object(slice_thickness, "localize_phantom", return_value=geometry),
            patch.object(slice_thickness, "_find_void_band", return_value=(100, 112)),
            patch.object(slice_thickness, "_find_septum", return_value=106),
            patch.object(
                slice_thickness,
                "_measure_ramp_fwhms",
                return_value=self._ramp_fit(58.0, 58.0),
            ),
            patch.object(slice_thickness, "render_annotated", return_value=None),
        ):
            result = slice_thickness.run(series)

        self.assertTrue(result.passed)
        self.assertTrue(any("preferred" in warning for warning in result.warnings))

    def test_slice_thickness_beyond_failure_boundary_fails(self):
        series = series_for(mapping={1: 0})
        geometry = PhantomGeometry(128.0, 128.0, 90.0, np.ones((256, 256), dtype=bool))
        with (
            patch.object(slice_thickness, "localize_phantom", return_value=geometry),
            patch.object(slice_thickness, "_find_void_band", return_value=(100, 112)),
            patch.object(slice_thickness, "_find_septum", return_value=106),
            patch.object(
                slice_thickness,
                "_measure_ramp_fwhms",
                return_value=self._ramp_fit(61.0, 61.0),
            ),
            patch.object(slice_thickness, "render_annotated", return_value=None),
        ):
            result = slice_thickness.run(series)

        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
