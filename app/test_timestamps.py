"""Test timestamp parsing for various formats"""
import unittest
from datetime import datetime
from app.test_import import parse_timestamp

class TestTimestampParsing(unittest.TestCase):
    def test_full_timestamp(self):
        """Test parsing full timestamp format"""
        ts = parse_timestamp("2023-07-11 21:17:07")
        self.assertEqual(ts.year, 2023)
        self.assertEqual(ts.month, 7)
        self.assertEqual(ts.day, 11)
        self.assertEqual(ts.hour, 21)
        self.assertEqual(ts.minute, 17)
        self.assertEqual(ts.second, 7)

    def test_12_hour_time(self):
        """Test parsing 12-hour time format"""
        ts = parse_timestamp("12:26 PM")
        self.assertEqual(ts.hour, 12)
        self.assertEqual(ts.minute, 26)

        ts = parse_timestamp("1:58 PM")
        self.assertEqual(ts.hour, 13)
        self.assertEqual(ts.minute, 58)

        ts = parse_timestamp("9:33 AM")
        self.assertEqual(ts.hour, 9)
        self.assertEqual(ts.minute, 33)

    def test_24_hour_time(self):
        """Test parsing 24-hour time format"""
        ts = parse_timestamp("13:26")
        self.assertEqual(ts.hour, 13)
        self.assertEqual(ts.minute, 26)

        ts = parse_timestamp("09:33")
        self.assertEqual(ts.hour, 9)
        self.assertEqual(ts.minute, 33)

    def test_invalid_timestamp(self):
        """Test handling of invalid timestamp format"""
        with self.assertRaises(ValueError):
            parse_timestamp("invalid")
        with self.assertRaises(ValueError):
            parse_timestamp("10 minutes")

if __name__ == "__main__":
    unittest.main()
