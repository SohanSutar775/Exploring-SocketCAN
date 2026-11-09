"""
can_common.py - shared helpers for the SocketCAN software-only demo.

Pure Python standard library (no python-can needed). Works on Linux only,
because AF_CAN / SocketCAN is part of the Linux kernel.

CAN message database used by every node
---------------------------------------
ID     Name           Fmt       Len  Rate     Signal layout
0x100  VehicleSpeed   Classic   2    100 ms   uint16 LE, factor 0.1 km/h, offset 0
0x101  EngineRPM      Classic   2     50 ms   uint16 LE, factor 1 rpm,    offset 0
0x102  CoolantTemp    Classic   1    500 ms   uint8,      factor 1 degC,  offset -40
0x200  VehicleDataFD  CAN FD    16   100 ms   speed u16 | rpm u16 | temp u8 | gear u8 | odometer u32 | 6 reserved
0x3A0  (unknown)      Classic   any  manual   NOT in the database - used for Challenge 3
"""
import socket
import struct
from collections import namedtuple

# ---- CAN identifier flags (linux/can.h) -----------------------------------
CAN_EFF_FLAG = 0x80000000   # extended (29-bit) frame format
CAN_RTR_FLAG = 0x40000000   # remote transmission request
CAN_ERR_FLAG = 0x20000000   # error message frame
CAN_SFF_MASK = 0x000007FF   # 11-bit standard identifier mask
CAN_EFF_MASK = 0x1FFFFFFF   # 29-bit extended identifier mask
CANFD_BRS = 0x01            # bit-rate switch (data phase at higher bit rate)
CANFD_ESI = 0x02            # error state indicator

# ---- Message identifiers --------------------------------------------------
ID_SPEED = 0x100
ID_RPM = 0x101
ID_TEMP = 0x102
ID_FD_VEHICLE = 0x200
ID_UNKNOWN_DEMO = 0x3A0

KNOWN_IDS = {
    ID_SPEED: "VehicleSpeed",
    ID_RPM: "EngineRPM",
    ID_TEMP: "CoolantTemp",
    ID_FD_VEHICLE: "VehicleDataFD",
}

# ---- Kernel frame layouts (struct can_frame / struct canfd_frame) ----------
CLASSIC_FMT = "=IB3x8s"      # can_id, len, pad/res (3 bytes), data[8]  = 16 bytes
FD_FMT = "=IBB2x64s"         # can_id, len, flags, res0, res1, data[64] = 72 bytes
CLASSIC_SIZE = struct.calcsize(CLASSIC_FMT)   # 16
FD_SIZE = struct.calcsize(FD_FMT)             # 72

Frame = namedtuple("Frame", "can_id extended fd brs length data")

# Valid CAN FD payload lengths (DLC codes 9..15 map to 12..64)
FD_VALID_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


# ---- Signal encode / decode ------------------------------------------------
def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def encode_speed(kmh):
    """km/h -> 2 bytes (uint16 little-endian, 0.1 km/h per bit)."""
    return struct.pack("<H", int(round(clamp(kmh, 0, 120) * 10)))


def decode_speed(data):
    return struct.unpack_from("<H", data, 0)[0] / 10.0


def encode_rpm(rpm):
    """rpm -> 2 bytes (uint16 little-endian, 1 rpm per bit)."""
    return struct.pack("<H", int(round(clamp(rpm, 800, 5000))))


def decode_rpm(data):
    return float(struct.unpack_from("<H", data, 0)[0])


def encode_temp(celsius):
    """degC -> 1 byte (raw = degC + 40, range -40..215)."""
    return struct.pack("<B", int(round(clamp(celsius, 20, 120))) + 40)


def decode_temp(data):
    return float(struct.unpack_from("<B", data, 0)[0] - 40)


def encode_fd_vehicle(kmh, rpm, celsius, gear, odometer_m):
    """16-byte CAN FD payload carrying all signals + gear + odometer."""
    return struct.pack(
        "<HHBBI6x",
        int(round(clamp(kmh, 0, 120) * 10)),
        int(round(clamp(rpm, 800, 5000))),
        int(round(clamp(celsius, 20, 120))) + 40,
        int(gear) & 0xFF,
        int(odometer_m) & 0xFFFFFFFF,
    )


def decode_fd_vehicle(data):
    spd, rpm, t_raw, gear, odo = struct.unpack_from("<HHBBI", data, 0)
    return {"speed": spd / 10.0, "rpm": float(rpm), "temp": float(t_raw - 40),
            "gear": gear, "odometer_m": odo}


# ---- Socket helpers --------------------------------------------------------
def open_can_socket(iface, fd=False, filters=None):
    """
    Open a raw SocketCAN socket bound to `iface` (e.g. 'vcan0').

    fd      : enable CAN FD frames (interface MTU must be 72: `ip link set vcan0 mtu 72`)
    filters : list of (can_id, can_mask) tuples -> kernel-level receive filter.
              None = receive everything (kernel default).
    """
    s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    if fd:
        s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FD_FRAMES, 1)
    if filters is not None:
        raw = b"".join(struct.pack("=II", cid, mask) for cid, mask in filters)
        s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, raw)
    s.bind((iface,))
    return s


def exact_filter(can_id, extended=False):
    """Filter matching exactly one identifier AND its frame format (std/ext)."""
    if extended:
        return (can_id | CAN_EFF_FLAG, CAN_EFF_MASK | CAN_EFF_FLAG | CAN_RTR_FLAG)
    return (can_id, CAN_SFF_MASK | CAN_EFF_FLAG | CAN_RTR_FLAG)


def pack_frame(can_id, data, fd=False, brs=True, extended=False):
    """Build the raw bytes for a classic or CAN FD frame."""
    if extended or can_id > CAN_SFF_MASK:
        can_id |= CAN_EFF_FLAG
    if fd:
        if len(data) not in FD_VALID_LENGTHS:
            raise ValueError("CAN FD length must be one of %s" % (FD_VALID_LENGTHS,))
        flags = CANFD_BRS if brs else 0
        return struct.pack(FD_FMT, can_id, len(data), flags, data.ljust(64, b"\x00"))
    if len(data) > 8:
        raise ValueError("Classic CAN carries at most 8 data bytes")
    return struct.pack(CLASSIC_FMT, can_id, len(data), data.ljust(8, b"\x00"))


def unpack_frame(raw):
    """Parse bytes returned by recv() into a Frame (handles classic and FD)."""
    if len(raw) == CLASSIC_SIZE:
        can_id, length, data = struct.unpack(CLASSIC_FMT, raw)
        fd, brs = False, False
    elif len(raw) == FD_SIZE:
        can_id, length, flags, data = struct.unpack(FD_FMT, raw)
        fd, brs = True, bool(flags & CANFD_BRS)
    else:
        raise ValueError("Unexpected frame size: %d bytes" % len(raw))
    extended = bool(can_id & CAN_EFF_FLAG)
    ident = can_id & (CAN_EFF_MASK if extended else CAN_SFF_MASK)
    return Frame(ident, extended, fd, brs, length, data[:length])


def send_frame(sock, can_id, data, fd=False, brs=True, extended=False):
    sock.send(pack_frame(can_id, data, fd=fd, brs=brs, extended=extended))


def recv_frame(sock):
    """Read one frame. Raises BlockingIOError if the socket is non-blocking and empty."""
    return unpack_frame(sock.recv(FD_SIZE))
