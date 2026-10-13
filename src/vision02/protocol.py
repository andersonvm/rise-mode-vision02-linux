"""Protocolo identificado por capturas USB de uma Vision 02 (0a00:1000)."""
from __future__ import annotations

REPORT_SIZE = 512
PREFIX = b"CRT\x00\x00"
KEY_SIGNATURE = b"ACK\x00\x00OK\x00\x00"
DISPLAY_COUNT = 15

# Sequência validada empiricamente no Ubuntu. Sem conclusões sobre cada comando.
INIT_PAYLOADS = (
    b"DIS",
    b"LIG\x00\x00\x19",
    bytes.fromhex("51 55 43 4d 44 11 11 00 11 00 11"),
    b"LIG\x00\x00\x19",
)


def command(payload: bytes) -> bytes:
    if len(PREFIX) + len(payload) > REPORT_SIZE:
        raise ValueError("Comando maior que 512 bytes")
    return (PREFIX + payload).ljust(REPORT_SIZE, b"\x00")


def image_reports(display_id: int, jpeg: bytes):
    """Um cabeçalho BAT seguido por fragmentos JPEG, cada um de 512 bytes."""
    if not 1 <= display_id <= DISPLAY_COUNT:
        raise ValueError("ID BAT deve estar entre 1 e 15")
    if not (4 <= len(jpeg) <= 65535):
        raise ValueError("JPEG deve ter entre 4 e 65535 bytes")
    if not jpeg.startswith(bytes.fromhex("ffd8")) or not jpeg.endswith(bytes.fromhex("ffd9")):
        raise ValueError("Dados não parecem um JPEG completo")
    header = PREFIX + b"BAT\x00\x00" + len(jpeg).to_bytes(2, "big") + bytes((display_id,))
    yield header.ljust(REPORT_SIZE, b"\x00")
    for offset in range(0, len(jpeg), REPORT_SIZE):
        yield jpeg[offset:offset + REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


def parse_key_report(data: bytes) -> tuple[int, bool] | None:
    if len(data) != REPORT_SIZE or data[:9] != KEY_SIGNATURE:
        return None
    key, state = data[9], data[10]
    if not (1 <= key <= DISPLAY_COUNT) or state not in (0, 1):
        return None
    return key, bool(state)


# Índice da tecla física em linhas de cima para baixo, esquerda para direita.
# Observado para os eventos em teste sequencial de teclas; confirmar caso o
# equipamento tenha perfil/configuração com ordem distinta.
def physical_key_to_display_id(key_id: int) -> int:
    if not 1 <= key_id <= DISPLAY_COUNT:
        raise ValueError("Tecla deve estar entre 1 e 15")
    row, col = divmod(key_id - 1, 5)
    return (2 - row) * 5 + col + 1
