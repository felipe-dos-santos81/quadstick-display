"""Waveshare e-paper hardware adapter.

This is the only module in the package that imports ``waveshare_epd``.
The driver module pulls in Raspberry Pi GPIO/SPI libraries at import
time, so the import happens lazily inside ``WaveshareDisplay.__init__``:
importing this module (like the tests do on non-Pi hosts) must not load
the driver.
"""
import logging
import time

from quadstick_display.controller import DisplayFrame, DisplaySize


class WaveshareDisplay:
    """``DisplayDevice`` for the Waveshare 4.2-inch B/C e-paper panel."""

    def __init__(self):
        from waveshare_epd import epd4in2bc

        self._epd = epd4in2bc.EPD()
        # Preserve the production wiring: the logical display width is the
        # driver's height, and the logical height is the driver's width.
        self._size = DisplaySize(width=self._epd.height, height=self._epd.width)

    @property
    def size(self) -> DisplaySize:
        return self._size

    def initialize(self) -> None:
        logging.info("Initializing e-Paper display")
        self._epd.init()
        self._epd.Clear()

    def show(self, frame: DisplayFrame) -> None:
        logging.info("Displaying content on e-Paper display")
        self._epd.display(
            imageblack=self._epd.getbuffer(frame.black),
            imagered=self._epd.getbuffer(frame.red),
        )
        time.sleep(2)
