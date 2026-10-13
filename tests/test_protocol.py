import io
import unittest
from PIL import Image
from vision02.display import encode_image
from vision02.protocol import (INIT_PAYLOADS, REPORT_SIZE, command, image_reports, parse_key_report, physical_key_to_display_id)


class TestProtocol(unittest.TestCase):
    def test_command_size(self):
        self.assertEqual(len(command(INIT_PAYLOADS[0])), REPORT_SIZE)
        self.assertEqual(command(b"DIS")[:8], b"CRT\x00\x00DIS")

    def test_image_packets(self):
        jpeg = encode_image(Image.new("RGB", (100, 100), "red"))
        packets = list(image_reports(11, jpeg))
        self.assertTrue(all(len(p) == REPORT_SIZE for p in packets))
        self.assertEqual(packets[0][:10], b"CRT\x00\x00BAT\x00\x00")
        self.assertEqual(int.from_bytes(packets[0][10:12], "big"), len(jpeg))
        self.assertEqual(packets[0][12], 11)
        self.assertEqual(b"".join(packets[1:])[:len(jpeg)], jpeg)

    def test_key(self):
        report = b"ACK\x00\x00OK\x00\x00" + bytes((3, 1))
        self.assertEqual(parse_key_report(report.ljust(512, b"\x00")), (3, True))
        self.assertEqual(parse_key_report(report[:10]), None)

    def test_mapping(self):
        self.assertEqual([physical_key_to_display_id(k) for k in range(1, 16)], [11,12,13,14,15,6,7,8,9,10,1,2,3,4,5])

    def test_jpeg_rotation(self):
        im = Image.new("RGB", (100, 100), "black")
        im.putpixel((3, 3), (255, 0, 0))
        jpeg = encode_image(im, quality=100)
        out = Image.open(io.BytesIO(jpeg))
        self.assertGreater(out.getpixel((96, 96))[0], 90)
        self.assertLess(out.getpixel((3, 3))[0], 90)


if __name__ == "__main__":
    unittest.main()
