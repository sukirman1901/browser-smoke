import sys
import unittest
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from PIL import Image

from tools.image_diff import compare_png


def _png(size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class ImageDiffTests(unittest.TestCase):
    def test_identical(self):
        png = _png((16, 16), (255, 0, 0, 255))
        result = compare_png(png, png)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["diff_pixels"], 0)
        self.assertEqual(result["diff_png"], b"")

    def test_size_mismatch_does_not_crash(self):
        result = compare_png(_png((16, 16), (0, 0, 0, 255)), _png((32, 16), (0, 0, 0, 255)))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["baseline_size"], [16, 16])
        self.assertEqual(result["current_size"], [32, 16])

    def test_pixel_diff(self):
        a = _png((8, 8), (0, 0, 0, 255))
        b = _png((8, 8), (255, 255, 255, 255))
        result = compare_png(a, b)
        self.assertEqual(result["status"], "diff")
        self.assertGreater(result["diff_pixels"], 0)
        self.assertTrue(result["diff_png"].startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
