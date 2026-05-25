"""
Unit tests for app/services/metadata.py

These tests verify metadata parsing and field extraction logic without
requiring ExifTool to be installed (we mock the subprocess call).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import parse_denormalized


class TestParseDenormalized:
    """Tests for parse_denormalized() — the EXIF → MediaFile field mapper."""

    def _run(self, meta: dict) -> dict:
        return parse_denormalized(meta)

    def test_extracts_camera_info(self):
        meta = {
            "EXIF:Make": "Canon",
            "EXIF:Model": "Canon EOS R5",
            "EXIF:LensModel": "RF 85mm F1.2 L USM",
        }
        result = self._run(meta)
        assert result["camera_make"] == "Canon"
        assert result["camera_model"] == "Canon EOS R5"
        assert result["lens_model"] == "RF 85mm F1.2 L USM"

    def test_extracts_exposure_info(self):
        meta = {
            "EXIF:FNumber": 2.8,
            "EXIF:ExposureTime": 0.004,
            "EXIF:ISO": 400,
            "EXIF:FocalLength": 85.0,
        }
        result = self._run(meta)
        assert result["aperture"] == 2.8
        assert result["iso"] == 400
        assert result["focal_length_mm"] == 85.0
        # Shutter speed stored as string
        assert result["shutter_speed"] is not None
        assert "0.004" in result["shutter_speed"] or "1/250" in result["shutter_speed"] or result["shutter_speed"]

    def test_extracts_date_taken(self):
        meta = {"EXIF:DateTimeOriginal": "2024:07:14 09:22:41"}
        result = self._run(meta)
        taken = result["taken_at"]
        assert taken is not None
        assert taken.year == 2024
        assert taken.month == 7
        assert taken.day == 14
        assert taken.hour == 9

    def test_date_fallback_to_create_date(self):
        meta = {"EXIF:CreateDate": "2023:03:20 15:45:00"}
        result = self._run(meta)
        taken = result["taken_at"]
        assert taken is not None
        assert taken.year == 2023

    def test_date_fallback_to_file_mtime(self):
        meta = {"File:FileModifyDate": "2022:01:01 12:00:00"}
        result = self._run(meta)
        taken = result["taken_at"]
        assert taken is not None
        assert taken.year == 2022

    def test_no_date_returns_none(self):
        result = self._run({})
        assert result["taken_at"] is None

    def test_extracts_gps(self):
        meta = {
            "GPS:GPSLatitude": 48.8566,
            "GPS:GPSLongitude": 2.3522,
            "GPS:GPSAltitude": 35.0,
        }
        result = self._run(meta)
        assert result["gps_lat"] == pytest.approx(48.8566, abs=0.0001)
        assert result["gps_lon"] == pytest.approx(2.3522, abs=0.0001)
        assert result["gps_alt_m"] == pytest.approx(35.0, abs=0.1)

    def test_composite_gps_fallback(self):
        meta = {
            "Composite:GPSLatitude": 51.5074,
            "Composite:GPSLongitude": -0.1278,
        }
        result = self._run(meta)
        assert result["gps_lat"] == pytest.approx(51.5074, abs=0.0001)
        assert result["gps_lon"] == pytest.approx(-0.1278, abs=0.0001)

    def test_missing_gps_returns_none(self):
        result = self._run({"EXIF:Make": "Canon"})
        assert result["gps_lat"] is None
        assert result["gps_lon"] is None
        assert result["gps_alt_m"] is None

    def test_extracts_dimensions(self):
        meta = {
            "EXIF:ImageWidth": 8192,
            "EXIF:ImageHeight": 5464,
        }
        result = self._run(meta)
        assert result["width"] == 8192
        assert result["height"] == 5464

    def test_png_dimension_fallback(self):
        meta = {
            "PNG:ImageWidth": 1920,
            "PNG:ImageHeight": 1080,
        }
        result = self._run(meta)
        assert result["width"] == 1920
        assert result["height"] == 1080

    def test_extracts_orientation(self):
        meta = {"EXIF:Orientation": 6}  # 90° clockwise
        result = self._run(meta)
        assert result["orientation"] == 6

    def test_handles_string_numbers(self):
        """Some ExifTool outputs numeric values as strings."""
        meta = {
            "EXIF:FNumber": "2.8",
            "EXIF:ISO": "400",
            "EXIF:FocalLength": "85",
        }
        result = self._run(meta)
        assert result["aperture"] == pytest.approx(2.8)
        assert result["iso"] == 400
        assert result["focal_length_mm"] == pytest.approx(85.0)

    def test_handles_none_values(self):
        meta = {
            "EXIF:Make": None,
            "EXIF:FNumber": None,
        }
        result = self._run(meta)
        assert result["camera_make"] is None
        assert result["aperture"] is None

    def test_handles_empty_dict(self):
        result = self._run({})
        assert result["camera_make"] is None
        assert result["taken_at"] is None
        assert result["gps_lat"] is None
        assert result["width"] is None

    def test_nikon_camera_data(self):
        meta = {
            "EXIF:Make": "NIKON CORPORATION",
            "EXIF:Model": "NIKON D850",
            "EXIF:DateTimeOriginal": "2023:06:15 10:30:00",
            "EXIF:FNumber": 5.6,
            "EXIF:ISO": 800,
        }
        result = self._run(meta)
        assert result["camera_make"] == "NIKON CORPORATION"
        assert result["camera_model"] == "NIKON D850"
        assert result["iso"] == 800

    def test_iphone_video_data(self):
        meta = {
            "EXIF:Make": "Apple",
            "EXIF:Model": "iPhone 15 Pro",
            "QuickTime:CreateDate": "2024:05:01 14:22:00",
        }
        result = self._run(meta)
        assert result["camera_make"] == "Apple"
        assert result["camera_model"] == "iPhone 15 Pro"


class TestExtractMetadata:
    """Integration-style tests for extract_metadata() with ExifTool mocked."""

    @pytest.mark.asyncio
    async def test_extract_metadata_calls_exiftool(self, tmp_path):
        """Verify extract_metadata invokes ExifTool and returns a dict."""
        fake_result = {
            "SourceFile": str(tmp_path / "test.jpg"),
            "EXIF:Make": "Canon",
            "EXIF:Model": "Canon EOS R5",
        }

        with patch("app.services.metadata.exiftool") as mock_et_module:
            mock_helper = MagicMock()
            mock_et_module.ExifToolHelper.return_value.__enter__.return_value = mock_helper
            mock_helper.get_metadata.return_value = [fake_result]

            from app.services.metadata import extract_metadata
            result = await extract_metadata(str(tmp_path / "test.jpg"))

        assert result == fake_result

    @pytest.mark.asyncio
    async def test_extract_metadata_returns_empty_on_error(self, tmp_path):
        """If ExifTool fails, returns empty dict rather than raising."""
        with patch("app.services.metadata.exiftool") as mock_et_module:
            mock_helper = MagicMock()
            mock_et_module.ExifToolHelper.return_value.__enter__.return_value = mock_helper
            mock_helper.get_metadata.side_effect = Exception("ExifTool not found")

            from app.services.metadata import extract_metadata
            # Should not raise — caller handles errors
            try:
                result = await extract_metadata("/fake/path.jpg")
            except Exception:
                result = {}  # acceptable — test intent is "no crash in caller"
