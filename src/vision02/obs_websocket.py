"""OBS WebSocket 5.x, JSON RFC6455, local e sem dependências adicionais.

Todas as chamadas de rede pertencem à thread OBS. Nenhum acesso a HID.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
from typing import Any


class OBSError(RuntimeError):
    pass


def config_path() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')) / 'vision02' / 'obs.json'


def read_config(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else config_path()
    if path.is_symlink():
        raise OBSError('Configuração OBS não pode ser link simbólico')
    if not path.exists():
        raise OBSError(f'Configure OBS em {path} (permissões 0600)')
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise OBSError('Configuração OBS deve pertencer ao usuário e ter permissões 0600')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise OBSError('Configuração OBS inválida')
    if set(data) - {'host', 'port', 'password', 'mic_input', 'desktop_input'}:
        raise OBSError('Campos desconhecidos em obs.json')
    host = data.get('host', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise OBSError('A conexão OBS aceita apenas localhost')
    port = data.get('port', 4455)
    if type(port) is not int or not 1 <= port <= 65535:
        raise OBSError('Porta OBS inválida')
    if not isinstance(data.get('password', ''), str):
        raise OBSError('Senha OBS inválida')
    for name in ('mic_input', 'desktop_input'):
        if name in data and (not isinstance(data[name], str) or not data[name].strip()):
            raise OBSError(f'{name} inválido')
    return {'host': host, 'port': port, 'password': data.get('password', ''),
            'mic_input': data.get('mic_input'), 'desktop_input': data.get('desktop_input')}


def make_auth(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode('utf-8')).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode('utf-8')).digest()).decode('ascii')


class OBSConnection:
    """Cliente síncrono; usar exclusivamente na thread dedicada ao OBS."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._id = 0

    @classmethod
    def connect(cls, config: dict, timeout: float = 2.0):
        sock = socket.create_connection((config['host'], config['port']), timeout=timeout)
        sock.settimeout(timeout)
        conn = cls(sock)
        try:
            key = base64.b64encode(secrets.token_bytes(16)).decode('ascii')
            host = config['host']
            if ':' in host:
                host = f'[{host}]'
            request = (f'GET / HTTP/1.1\r\nHost: {host}:{config["port"]}\r\n'
                       'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                       f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                       'Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n')
            sock.sendall(request.encode('ascii'))
            answer = bytearray()
            while b'\r\n\r\n' not in answer:
                if len(answer) > 8192:
                    raise OBSError('Resposta HTTP WebSocket excessiva')
                chunk = sock.recv(1)
                if not chunk:
                    raise OBSError('OBS encerrou o handshake HTTP')
                answer.extend(chunk)
            lines = answer.decode('iso-8859-1').split('\r\n')
            if not lines[0].startswith('HTTP/1.1 101'):
                raise OBSError('OBS recusou a conexão WebSocket')
            headers = dict((k.strip().lower(), v.strip()) for line in lines[1:]
                           if ':' in line for k, v in [line.split(':', 1)])
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if headers.get('sec-websocket-accept') != expected:
                raise OBSError('Handshake WebSocket inválido')
            if headers.get('sec-websocket-protocol') != 'obswebsocket.json':
                raise OBSError('Subprotocolo OBS JSON não negociado')
            hello = conn.recv_json()
            if hello.get('op') != 0:
                raise OBSError('OBS não enviou Hello')
            data = hello.get('d', {})
            auth = data.get('authentication')
            identify = {'rpcVersion': 1, 'eventSubscriptions': 0}
            if auth is not None:
                identify['authentication'] = make_auth(config['password'], auth['salt'], auth['challenge'])
            conn.send_json({'op': 1, 'd': identify})
            reply = conn.recv_json()
            if reply.get('op') != 2:
                raise OBSError('Identificação OBS rejeitada; confira a senha')
            return conn
        except BaseException:
            sock.close()
            raise

    def close(self):
        self.sock.close()

    def _send_frame(self, opcode: int, content: bytes):
        if len(content) > 2_000_000:
            raise OBSError('Mensagem WebSocket grande demais')
        header = bytearray([0x80 | opcode])
        length = len(content)
        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack('!H', length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack('!Q', length))
        mask = secrets.token_bytes(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(content))
        self.sock.sendall(bytes(header) + mask + masked)

    def _read_exact(self, n: int) -> bytes:
        result = bytearray()
        while len(result) < n:
            piece = self.sock.recv(n - len(result))
            if not piece:
                raise ConnectionError('Conexão OBS encerrada')
            result.extend(piece)
        return bytes(result)

    def recv_json(self) -> dict:
        fragments = bytearray()
        while True:
            b1, b2 = self._read_exact(2)
            opcode = b1 & 0x0f
            if b1 & 0x70 or b2 & 0x80:
                raise OBSError('Frame WebSocket inválido')
            size = b2 & 0x7f
            if size == 126:
                size = struct.unpack('!H', self._read_exact(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', self._read_exact(8))[0]
            if size > 2_000_000 or len(fragments) + size > 2_000_000:
                raise OBSError('Mensagem OBS grande demais')
            payload = self._read_exact(size)
            if opcode == 9:
                self._send_frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 8:
                raise ConnectionError('OBS encerrou o WebSocket')
            if opcode not in (0, 1) or (opcode == 0 and not fragments):
                raise OBSError('Frame WebSocket inesperado')
            fragments.extend(payload)
            if b1 & 0x80:
                result = json.loads(fragments.decode('utf-8'))
                if not isinstance(result, dict):
                    raise OBSError('Resposta OBS não é objeto')
                return result

    def send_json(self, obj: dict):
        self._send_frame(1, json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))

    def call(self, name: str, data: dict | None = None) -> dict:
        self._id += 1
        request_id = str(self._id)
        payload: dict[str, Any] = {'requestType': name, 'requestId': request_id}
        if data:
            payload['requestData'] = data
        self.send_json({'op': 6, 'd': payload})
        # Eventos não são solicitados; ignore eventuais mensagens atrasadas.
        for _ in range(32):
            reply = self.recv_json()
            if reply.get('op') != 7 or reply.get('d', {}).get('requestId') != request_id:
                continue
            result = reply['d']
            status = result.get('requestStatus', {})
            if status.get('result') is not True:
                raise OBSError(f'{name}: {status.get("comment") or status.get("code") or "falha"}')
            return result.get('responseData', {})
        raise OBSError('Limite de respostas OBS fora de ordem excedido')


def main(argv=None):
    """Verificação offline do HID: testa somente autenticação e API OBS."""
    import argparse
    parser = argparse.ArgumentParser(description='Verifica a conexão local com OBS WebSocket 5.x')
    parser.parse_args(argv)
    connection = None
    try:
        config = read_config()
        connection = OBSConnection.connect(config)
        version = connection.call('GetVersion')
        print(json.dumps({'connected': True, 'obsVersion': version.get('obsVersion'),
                          'webSocketVersion': version.get('obsWebSocketVersion')}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, OBSError) as exc:
        parser.error(str(exc))
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    main()
