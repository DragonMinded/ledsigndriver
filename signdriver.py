from abc import ABC
import serial  # type: ignore

from typing import Dict, Optional, Sequence


class ConfigurationManager:

    def __init__(self, sign: "LEDSign") -> None:
        self.__sign = sign
        self.__accum: Dict[str, bytes] = {}

    def __enter__(self) -> "ConfigurationManager":
        return self

    def __exit__(self, type: object, value: object, traceback: object) -> None:
        if type is None:
            # Success, update config
            self.__sign._send_command(
                b"E$" +
                b"".join([val for _, val in self.__accum.items()])
            )

    def set_text(self, label: str, size: int) -> None:
        """
        Set a particular page identified by label to be a text page, with
        maximum length size.
        """

        self.__sign._check_label(label)
        if label == '0':
            raise Exception("Cannot use priority label in text configuration!")
        self.__accum[label] = (
            str(label).encode("ascii") +
            b"A" +  # Text mode
            b"L" +  # Locked for remote editing
            self.__sign._make_hex(size, 4) +  # Length of data
            b"FF00"  # Start always, never end.
        )

    def set_string(self, label: str, size: int) -> None:
        """
        Set a particular page identified by label to be a string page, with
        maximum length size.
        """

        self.__sign._check_label(label)
        if label == '0' or label == "?":
            raise Exception("Cannot use priority label in string configuration!")
        if size > 125:
            raise Exception("Strings must be 125 bytes or shorter!")
        self.__accum[label] = (
            str(label).encode("ascii") +
            b"B" +  # String mode
            b"L" +  # Locked for remote editing
            self.__sign._make_hex(size, 4) +  # Length of data
            b"0000"  # Padding for string command
        )

    def set_picture(self, label: str, width: int, height: int, colors: int = 1) -> None:
        """
        Set a particular page identified by label to be a picture page,
        with width and height specified for the picture.
        """

        self.__sign._check_label(label)
        if label == '0':
            raise Exception("Cannot use priority label in picture configuration!")
        if width > 255 or height > 31:
            raise Exception("Picture size must be at most 31x255!")
        if colors not in {1, 3, 8}:
            raise Exception("Picture must be either 1, 3 or 8 colors!")
        if colors == 1:
            size = b"1000"
        elif colors == 2:
            size = b"2000"
        else:
            size = b"4000"

        self.__accum[label] = (
            str(label).encode("ascii") +
            b"D" +  # String mode
            b"L" +  # Locked for remote editing
            self.__sign._make_hex(height, 2) +
            self.__sign._make_hex(width, 2) +
            size
        )


class BaseFormat(ABC):
    """
    Type-only class that all format specifiers subclass from.
    """

    SUPPORTS_FLASH = 0x1
    SUPPORTS_COLOR = 0x2

    children: Sequence["BaseFormat"] = []

    def render(self, supportmask: int) -> bytes:
        ...


class Text(BaseFormat):
    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, supportmask: int) -> bytes:
        return self.text.encode('ascii')


class Small(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        return bytes([0x1A, 0x31]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x1A, 0x39])


class Flash(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        if supportmask & self.SUPPORTS_FLASH:
            return bytes([0x07, 0x31]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x07, 0x30])
        else:
            return b"".join(c.render(supportmask) for c in self.children)


class _Color(BaseFormat, ABC):

    def __init__(self, code: int, formatting: Sequence[BaseFormat]) -> None:
        self.code = code
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        if supportmask & self.SUPPORTS_COLOR:
            return bytes([0x1C, self.code]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x1C, 0x43])
        else:
            return b"".join(c.render(supportmask) for c in self.children)


class Red(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x31, formatting)


class Amber(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x32, formatting)


class Green(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x33, formatting)


class Striped(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x39, formatting)


class Mixed(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x41, formatting)


class String(BaseFormat):
    def __init__(self, label: str) -> None:
        # TODO: Really should validate the label
        self.label = label

    def render(self, supportmask: int) -> bytes:
        return bytes([0x10]) + self.label.encode('ascii')


class Picture(BaseFormat):
    def __init__(self, label: str) -> None:
        # TODO: Really should validate the label
        self.label = label

    def render(self, supportmask: int) -> bytes:
        return bytes([0x14]) + self.label.encode('ascii')


class LEDSign:

    # Codes from Sign manual
    PREAMBLE = bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    SOH = bytes([0x01])
    STX = bytes([0x02])
    EOT = bytes([0x04])
    ESC = bytes([0x1B])

    # Modes for displaying text
    ROTATE = b"a"
    HOLD = b"b"
    FLASH = b"c"
    ROLL_UP = b"e"
    ROLL_DOWN = b"f"
    ROLL_LEFT = b"g"
    ROLL_RIGHT = b"h"
    WIPE_UP = b"i"
    WIPE_DOWN = b"j"
    WIPE_LEFT = b"k"
    WIPE_RIGHT = b"l"
    SCROLL = b"m"
    AUTOMODE = b"o"
    ROLL_IN = b"p"
    ROLL_OUT = b"q"
    WIPE_IN = b"r"
    WIPE_OUT = b"s"
    COMPRESSED_ROTATE = b"t"
    EXPLODE = b"u"
    CLOCK = b"v"
    TWINKLE = b"n0"
    SPARKLE = b"n1"
    SNOW = b"n2"
    INTERLOCK = b"n3"
    SWITCH = b"n4"
    SLIDE = b"n5"
    SPRAY = b"n6"
    STARBURST = b"n7"
    WELCOME = b"n8"
    SLOT_MACHINE = b"n9"

    def __init__(self, port: str, address: Optional[int], *, supports_flash: bool = False, supports_color: bool = False) -> None:
        """
        Open a serial port similar to /dev/ttyUSB0 and address it with the
        address given. This can be 1-255 inclusive to address a sign that
        has an address (signs tell you their address on boot), or None to
        signify a broadcast address (talk to all signs).
        """

        self.port = port
        if address is not None:
            self.__check_address(address)
        self.address = address

        # 9600 9N1
        self.__serial = serial.Serial(port, 9600, timeout=1)

        # Support mask
        self.__mask = 0
        if supports_flash:
            self.__mask = self.__mask | BaseFormat.SUPPORTS_FLASH
        if supports_color:
            self.__mask = self.__mask | BaseFormat.SUPPORTS_COLOR

    def _make_hex(self, value: int, length: int) -> bytes:
        hexbytes = hex(value)[2:].encode("ascii")
        while(len(hexbytes) < length):
            hexbytes = b'0' + hexbytes
        return hexbytes

    def _send_command(self, command: bytes) -> None:
        self.__serial.write(
            self.PREAMBLE +
            self.SOH +
            b'Z' +
            self._make_hex(self.address or 0, 2) +
            self.STX +
            command +
            self.EOT
        )

    def __check_address(self, address: int) -> None:
        if address < 1 or address > 255:
            raise Exception("address must be between 1 and 255 inclusive!")

    def _check_label(self, label: str) -> None:
        if len(label) != 1:
            raise Exception("label must be a single character!")
        val = ord(label)
        if val < 0x20 or val > 0x7E:
            raise Exception("label must be a valid ascii character!")

    def __check_mode(self, mode: bytes) -> None:
        if mode not in {
            self.ROTATE,
            self.HOLD,
            self.FLASH,
            self.ROLL_UP,
            self.ROLL_DOWN,
            self.ROLL_LEFT,
            self.ROLL_RIGHT,
            self.WIPE_UP,
            self.WIPE_DOWN,
            self.WIPE_LEFT,
            self.WIPE_RIGHT,
            self.SCROLL,
            self.AUTOMODE,
            self.ROLL_IN,
            self.ROLL_OUT,
            self.WIPE_IN,
            self.WIPE_OUT,
            self.COMPRESSED_ROTATE,
            self.EXPLODE,
            self.CLOCK,
            self.TWINKLE,
            self.SPARKLE,
            self.SNOW,
            self.INTERLOCK,
            self.SWITCH,
            self.SLIDE,
            self.SPRAY,
            self.STARBURST,
            self.WELCOME,
            self.SLOT_MACHINE,
        }:
            raise Exception("mode selected is invalid!")

    def __make_text(self, text: str) -> bytes:
        return text.encode('ascii')

    def write_text(self, label: str, text: str, *, mode: Optional[bytes] = None) -> None:
        """
        Write raw text to a label that's been previously configured
        as text.
        """

        if len(text) < 1:
            raise Exception("text must be at least one character long!")
        self._check_label(label)
        self.__check_mode(mode or self.AUTOMODE)
        self._send_command(
            b'A' +
            str(label).encode("ascii") +
            self.ESC +
            b"0" +  # Fill all lines, center vertically
            (mode or self.AUTOMODE) +  # Animation mode
            self.__make_text(text)
        )

    def write_string(self, label: str, text: str) -> None:
        """
        Write raw text to a label that's been previously configured
        as a string.
        """

        if len(text) < 1:
            raise Exception("text must be at least one character long!")
        self._check_label(label)
        self._send_command(
            b'G' +
            str(label).encode("ascii") +
            self.__make_text(text)
        )

    def write_format(self, label: str, *formatting: BaseFormat, mode: Optional[bytes] = None) -> None:
        """
        Write formatted text to a label that's been previously configured
        as text.
        """

        if len(formatting) < 1:
            raise Exception("formatting must be at least one character long!")
        self._check_label(label)
        self.__check_mode(mode or self.AUTOMODE)
        self._send_command(
            b'A' +
            str(label).encode("ascii") +
            self.ESC +
            b"0" +  # Fill all lines, center vertically
            (mode or self.AUTOMODE) +  # Animation mode
            b"".join(fobj.render(self.__mask) for fobj in formatting)
        )

    def write_picture(self, label: str, picture: Sequence[Sequence[str]]) -> None:
        height = len(picture)
        width = len(picture[0])

        for row in picture:
            if len(row) != width:
                raise Exception("Picture must have identical width for every row!")
        self._check_label(label)

        def _color_lut(val: str) -> int:
            val = val.upper()
            if val == "-":
                return 0x30
            elif val == "R":
                return 0x31
            elif val == "G":
                return 0x32
            elif val == "A":
                return 0x33
            elif val == "r":
                return 0x34
            elif val == "g":
                return 0x35
            elif val == "a":
                return 0x36
            else:
                raise Exception(f"Illegal color {val} for picture!")

        self._send_command(
            b'I' +
            str(label).encode("ascii") +
            self._make_hex(height, 2) +
            self._make_hex(width, 2) +
            b"".join(bytes(_color_lut(val) for val in row) + b"\r\n" for row in picture)
        )

    def change_address(self, new_address: int) -> None:
        """
        Change sign address and then use that address.
        """

        self.__check_address(new_address)
        self._send_command(
            b'E' +
            b'7' +
            self._make_hex(new_address, 2)
        )
        self.address = new_address

    def clear_configuration(self) -> None:
        """
        Wipe all internal cycle information for all pages. After issuing
        this command, make sure to set configuration on a page before trying
        to write text, strings or pictures to it.
        """

        self._send_command(b"E$")

    def set_configuration(self) -> ConfigurationManager:
        """
        With block manager for configuring files on the system.
        """
        return ConfigurationManager(self)


if __name__ == "__main__":
    # Simple test program that will drive two signs connected over a RS232/RS485 connection.
    # I wrote this to test against a 4160R (flash support, no color) and a 4120R (no flash, but tricolor).
    # The 4160 is set to address 1 and 4120 is set to address 2 in this demo program.
    signs = {}
    for addr in [1, 2]:
        sign = LEDSign("/dev/ttyUSB0", addr, supports_flash=(addr == 1), supports_color=(addr == 2))
        sign.clear_configuration()
        with sign.set_configuration() as config:
            config.set_text("A", 64)
            config.set_string("B", 64)
            config.set_picture("C", 6, 6, colors=3)
        sign.write_string("B", ":3")
        sign.write_picture(
            "C",
            [
                "--RAGG",
                "--RAGG",
                "-RRAAG",
                "-RRAAG",
                "RRRAAA",
                "RRRAAA",
            ],
        )
        sign.write_format(
            "A",
            Small(
                Flash(
                    Red(Text("A")),
                    Amber(Text("B")),
                    Green(Text("C")),
                ),
                Mixed(Text("abc")),
            ),
            Striped(
                Text("ABC")
            ),
            Text("abc "),
            String("B"),
            Picture("C"),
        )
        signs[addr] = sign
