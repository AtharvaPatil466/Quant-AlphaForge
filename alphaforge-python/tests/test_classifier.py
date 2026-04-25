"""Tests for signal classifier."""

from scanner.classifier import classify_signal, classify_signal_js


class TestClassifySignal:
    def test_long(self):
        assert classify_signal(1.5) == "LONG"

    def test_short(self):
        assert classify_signal(-1.5) == "SHORT"

    def test_neutral(self):
        assert classify_signal(0.3) == "NEUTRAL"

    def test_custom_threshold(self):
        assert classify_signal(0.5, threshold=0.3) == "LONG"
        assert classify_signal(-0.5, threshold=0.3) == "SHORT"


class TestClassifySignalJS:
    def test_long(self):
        assert classify_signal_js(50) == "LONG"

    def test_short(self):
        assert classify_signal_js(-50) == "SHORT"

    def test_neutral(self):
        assert classify_signal_js(20) == "NEUTRAL"
