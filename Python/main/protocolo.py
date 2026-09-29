"""Protocolo de mensagens entre o Raspberry Pi, o PC de IA e o servidor (VM).

Cada mensagem: [tamanho do cabecalho: uint32][tamanho dos dados: uint32][cabecalho JSON][dados binarios]
O cabecalho sempre tem o campo "tipo". Os dados carregam, por exemplo, um quadro JPEG.

Tipos:
  hello   cliente -> servidor: {"papel": "ia"|"pi", "token": ..., "mesa": n}
  ok      resposta ao hello (o Pi envia a configuracao da mesa ao PC de IA)
  erro    resposta de recusa, seguida do fechamento da conexao
  quadro  {"mesa", "t", "largura", "altura"} + JPEG   (t = relogio do Pi, em segundos)
  status  {"mesa", "modo", "arduino": {...}, "fps", "latencia_ms"}
  cmd     {"mesa", "c": "1"|"2"|"3"|"r", "t": instante do quadro que originou o comando}
  ping    mantem a conexao viva
"""
import hmac
import json
import struct

MAX_CABECALHO = 64 * 1024
MAX_DADOS = 8 * 1024 * 1024


class ErroProtocolo(Exception):
    pass


def empacotar(cab, dados=b""):
    c = json.dumps(cab, separators=(",", ":")).encode("utf-8")
    return struct.pack("!II", len(c), len(dados)) + c + dados


def _validar(nc, nd):
    if nc == 0 or nc > MAX_CABECALHO or nd > MAX_DADOS:
        raise ErroProtocolo("mensagem com tamanho invalido")


def _lerExato(sock, n):
    buf = bytearray()
    while len(buf) < n:
        parte = sock.recv(n - len(buf))
        if not parte:
            raise ConnectionError("conexao encerrada")
        buf += parte
    return bytes(buf)


def enviar(sock, cab, dados=b""):
    sock.sendall(empacotar(cab, dados))


def receber(sock):
    nc, nd = struct.unpack("!II", _lerExato(sock, 8))
    _validar(nc, nd)
    cab = json.loads(_lerExato(sock, nc))
    dados = _lerExato(sock, nd) if nd else b""
    if not isinstance(cab, dict) or "tipo" not in cab:
        raise ErroProtocolo("cabecalho invalido")
    return cab, dados


async def receberAsync(reader):
    nc, nd = struct.unpack("!II", await reader.readexactly(8))
    _validar(nc, nd)
    cab = json.loads(await reader.readexactly(nc))
    dados = await reader.readexactly(nd) if nd else b""
    if not isinstance(cab, dict) or "tipo" not in cab:
        raise ErroProtocolo("cabecalho invalido")
    return cab, dados


def tokenValido(recebido, esperado):
    if not esperado or not isinstance(recebido, str):
        return False
    return hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8"))
