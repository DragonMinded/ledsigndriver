from abc import ABC
import serial  # type: ignore
import time

from typing import Dict, Optional, Sequence
from typing_extensions import Final


def _check_label(label: str) -> None:
    if len(label) != 1:
        raise Exception("label must be a single character!")
    val = ord(label)
    if val < 0x20 or val > 0x7E:
        raise Exception("label must be a valid ascii character!")


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

        _check_label(label)
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

        _check_label(label)
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

        _check_label(label)
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

    SUPPORTS_FLASH: Final[int] = 0x1
    SUPPORTS_COLOR: Final[int] = 0x2

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


class Fancy(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        return bytes([0x1A, 0x38]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x1A, 0x39])


class Wide(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        return bytes([0x12]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x11])


class Fixed(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        return bytes([0x1E, 0x31]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x1E, 0x30])


class Flash(BaseFormat):
    def __init__(self, *formatting: BaseFormat) -> None:
        self.children = formatting

    def render(self, supportmask: int) -> bytes:
        if supportmask & self.SUPPORTS_FLASH:
            return bytes([0x07, 0x31]) + b"".join(c.render(supportmask) for c in self.children) + bytes([0x07, 0x30])
        else:
            return b"".join(c.render(supportmask) for c in self.children)


def Newline() -> BaseFormat:
    return Text("\r")


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


class Green(_Color):
    def __init__(self, *formatting: BaseFormat) -> None:
        super().__init__(0x32, formatting)


class Amber(_Color):
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
        _check_label(label)
        self.label = label

    def render(self, supportmask: int) -> bytes:
        return bytes([0x10]) + self.label.encode('ascii')


class Picture(BaseFormat):
    def __init__(self, label: str) -> None:
        _check_label(label)
        self.label = label

    def render(self, supportmask: int) -> bytes:
        return bytes([0x14]) + self.label.encode('ascii')


class LEDSign:

    # Codes from Sign manual
    PREAMBLE: Final[bytes] = bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    SOH: Final[bytes] = bytes([0x01])
    STX: Final[bytes] = bytes([0x02])
    ETX: Final[bytes] = bytes([0x03])
    EOT: Final[bytes] = bytes([0x04])
    ESC: Final[bytes] = bytes([0x1B])

    # Modes for displaying text
    ROTATE: Final[bytes] = b"a"
    HOLD: Final[bytes] = b"b"
    FLASH: Final[bytes] = b"c"
    ROLL_UP: Final[bytes] = b"e"
    ROLL_DOWN: Final[bytes] = b"f"
    ROLL_LEFT: Final[bytes] = b"g"
    ROLL_RIGHT: Final[bytes] = b"h"
    WIPE_UP: Final[bytes] = b"i"
    WIPE_DOWN: Final[bytes] = b"j"
    WIPE_LEFT: Final[bytes] = b"k"
    WIPE_RIGHT: Final[bytes] = b"l"
    SCROLL: Final[bytes] = b"m"
    AUTOMODE: Final[bytes] = b"o"
    ROLL_IN: Final[bytes] = b"p"
    ROLL_OUT: Final[bytes] = b"q"
    WIPE_IN: Final[bytes] = b"r"
    WIPE_OUT: Final[bytes] = b"s"
    COMPRESSED_ROTATE: Final[bytes] = b"t"
    EXPLODE: Final[bytes] = b"u"
    CLOCK: Final[bytes] = b"v"
    TWINKLE: Final[bytes] = b"n0"
    SPARKLE: Final[bytes] = b"n1"
    SNOW: Final[bytes] = b"n2"
    INTERLOCK: Final[bytes] = b"n3"
    SWITCH: Final[bytes] = b"n4"
    SLIDE: Final[bytes] = b"n5"
    SPRAY: Final[bytes] = b"n6"
    STARBURST: Final[bytes] = b"n7"
    WELCOME: Final[bytes] = b"n8"
    SLOT_MACHINE: Final[bytes] = b"n9"

    # Sign types for overriding which sign to talk to, in the case of
    # updating the sign's address.
    ONLY_ONE_LINE_SIGNS: Final[bytes] = b"1"
    ONLY_TWO_LINE_SIGNS: Final[bytes] = b"2"
    ONLY_430i: Final[bytes] = b"C"
    ONLY_440i: Final[bytes] = b"D"
    ONLY_460i: Final[bytes] = b"E"
    ONLY_790i: Final[bytes] = b"U"
    ONLY_4120C: Final[bytes] = b"a"
    ONLY_4160C: Final[bytes] = b"b"
    ONLY_4200C: Final[bytes] = b"c"
    ONLY_4240C: Final[bytes] = b"d"
    ONLY_215R: Final[bytes] = b"e"
    ONLY_215C: Final[bytes] = b"f"
    ONLY_4120R: Final[bytes] = b"g"
    ONLY_4160R: Final[bytes] = b"h"
    ONLY_4200R: Final[bytes] = b"i"
    ONLY_4240R: Final[bytes] = b"j"
    ONLY_4080: Final[bytes] = b"t"
    ALL_SIGNS: Final[bytes] = b"Z"

    def __init__(self, port: str, address: Optional[int], *, supports_flash: bool = False, supports_color: bool = False) -> None:
        """
        Open a serial port similar to /dev/ttyUSB0 and address it with the
        address given. This can be 1-255 inclusive to address a sign that
        has an address (signs tell you their address on boot on the sign itself),
        or None to signify a broadcast address (talk to all signs).
        """

        self.port = port
        if address is not None:
            self.__check_address(address)
        self.address = address

        # 9600 8N1
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

    def _send_command(self, command: bytes, *, override_sign_types: Optional[bytes] = None) -> None:
        self.__serial.write(
            self.PREAMBLE +
            self.SOH +
            (override_sign_types if override_sign_types is not None else LEDSign.ALL_SIGNS) +
            self._make_hex(self.address or 0, 2) +
            self.STX +
            command +
            self.EOT
        )

    def __check_address(self, address: int) -> None:
        if address < 1 or address > 255:
            raise Exception("address must be between 1 and 255 inclusive!")

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

    def __unmake_text(self, text: bytes) -> str:
        return text.decode('ascii')

    def read_sign_type(self) -> bytes:
        """
        Read a sign and return its type, which can be used in a subsequent
        `change_address` call as the `override_sign_types` parameter.
        """

        self._send_command(b"F-")
        retval = b""
        old = time.time()
        while time.time() - old < 5.0:
            retval = retval + self.__serial.read()
            if self.PREAMBLE + self.SOH in retval and self.EOT in retval:
                _, rest = retval.split(self.PREAMBLE + self.SOH, 1)
                packet, _ = rest.split(self.EOT, 1)
                original_address, chunk = packet.split(self.STX, 1)
                if self.ETX in chunk:
                    response, _crc = chunk.split(self.ETX, 1)
                else:
                    response = chunk
                if response[:2] != b"E-":
                    raise Exception("Logic error! Got invalid response!")
                return response[2:3]
        raise Exception("Failed to read sign type!")

    def write_text(self, label: str, text: str, *, mode: Optional[bytes] = None) -> None:
        """
        Write raw text to a label that's been previously configured
        as text.
        """

        if len(text) < 1:
            raise Exception("text must be at least one character long!")
        _check_label(label)
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
        _check_label(label)
        self._send_command(
            b'G' +
            str(label).encode("ascii") +
            self.__make_text(text)
        )

    def read_string(self, label: str) -> str:
        """
        Read raw text from a label that's been previously configured
        as a string.
        """

        _check_label(label)
        self._send_command(
            b'H' +
            str(label).encode("ascii")
        )
        retval = b""
        old = time.time()
        while time.time() - old < 5.0:
            retval = retval + self.__serial.read()
            if self.PREAMBLE + self.SOH in retval and self.EOT in retval:
                _, rest = retval.split(self.PREAMBLE + self.SOH, 1)
                packet, _ = rest.split(self.EOT, 1)
                original_address, chunk = packet.split(self.STX, 1)
                if self.ETX in chunk:
                    response, _crc = chunk.split(self.ETX, 1)
                else:
                    response = chunk
                if response[:2] != (b"G" + str(label).encode("ascii")):
                    raise Exception("Logic error! Got invalid response!")
                return self.__unmake_text(response[2:])
        raise Exception(f"Failed to read string label {label}!")

    def write_format(self, label: str, *formatting: BaseFormat, mode: Optional[bytes] = None, split_animation: bool = False) -> None:
        """
        Write formatted text to a label that's been previously configured
        as text.
        """

        if len(formatting) < 1:
            raise Exception("formatting must be at least one character long!")
        _check_label(label)
        self.__check_mode(mode or self.AUTOMODE)

        # Do some shenanigans so we can display full-height photos
        data = b"".join(fobj.render(self.__mask) for fobj in formatting).split(b"\r")
        if len(data) == 1 or not split_animation:
            fixeddata = (
                self.ESC +
                b"0" +  # Fill all lines, center vertically
                (mode or self.AUTOMODE) +  # Animation mode
                b"\r".join(data)
            )
        else:
            # Split the animation in half
            total = len(data)
            top = total // 2
            fixeddata = (
                self.ESC +
                b"\"" +  # Top line only
                (mode or self.AUTOMODE) +  # Animation mode
                b"\r".join(data[:top]) +
                self.ESC +
                b"&" +  # Bottom line only
                (mode or self.AUTOMODE) +  # Animation mode
                b"\r".join(data[top:])
            )

        self._send_command(
            b'A' +
            str(label).encode("ascii") +
            self.ESC +
            b"0" +  # Fill all lines, center vertically
            (mode or self.AUTOMODE) +  # Animation mode
            fixeddata
        )

    def write_picture(self, label: str, picture: Sequence[Sequence[str]]) -> None:
        height = len(picture)
        width = len(picture[0])

        for row in picture:
            if len(row) != width:
                raise Exception("Picture must have identical width for every row!")
        _check_label(label)

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

    def change_address(self, new_address: int, *, override_sign_types: Optional[bytes] = None) -> None:
        """
        Change sign address and then use that address.
        """

        self.__check_address(new_address)
        self._send_command(
            b'E' +
            b'7' +
            self._make_hex(new_address, 2),
            override_sign_types=override_sign_types,
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
    # The 4160 is set to address 1 and 4120 is set to address 2 in this demo program. In order
    # to test readback functionality, it will read and print the text in label "B" which should be
    # ":3" as set by this test program itself.
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
        print("Sign B text is", sign.read_string("B"))
