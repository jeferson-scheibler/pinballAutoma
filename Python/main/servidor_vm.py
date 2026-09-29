"""Servidor das mesas de pinball para a VM (IP publico). Usa somente a biblioteca padrao.

- Porta do Pi (TLS): recebe o status, o placar e o video reduzido enviados pelo Raspberry Pi.
- Porta web (HTTPS + senha): pagina com o video e o placar das mesas e o botao de zerar placar.

A VM nao aciona os solenoides: o unico comando que ela repassa ao Pi e zerar o placar.

Variaveis de ambiente:
  PINBALL_TOKEN_VM     token que o Pi usa para se conectar (o mesmo configurado no Pi)
  PINBALL_WEB_USUARIO  usuario da pagina web
  PINBALL_WEB_SENHA    senha da pagina web

Uso: python servidor_vm.py --cert servidor.crt --chave servidor.key
"""
import argparse
import asyncio
import base64
import hmac
import json
import logging
import os
import re
import ssl
import time

import protocolo

log = logging.getLogger("servidor_vm")


class Estado:
    def __init__(self):
        self.pi = None            # writer da conexao atual do Pi
        self.piDesde = None
        self.mesas = {}           # id -> {"status", "recebido", "jpeg", "versao"}
        self.novoQuadro = asyncio.Condition()

    def mesa(self, mid):
        return self.mesas.setdefault(mid, {"status": None, "recebido": None, "jpeg": None, "versao": 0})


estado = None


# ---------------------------------------------------------------------------- conexao do Pi

async def atenderPi(reader, writer, token):
    peer = writer.get_extra_info("peername")
    try:
        cab, _ = await asyncio.wait_for(protocolo.receberAsync(reader), 10)
        if cab.get("tipo") != "hello" or cab.get("papel") != "pi" or not protocolo.tokenValido(cab.get("token"), token):
            log.warning("conexao recusada de %s: token invalido", peer)
            writer.write(protocolo.empacotar({"tipo": "erro", "motivo": "acesso negado"}))
            await writer.drain()
            return
        if estado.pi is not None:
            log.info("nova conexao do Pi substitui a anterior")
            estado.pi.close()
        estado.pi = writer
        estado.piDesde = time.time()
        for mid in cab.get("mesas", []):
            estado.mesa(mid)
        writer.write(protocolo.empacotar({"tipo": "ok"}))
        await writer.drain()
        log.info("Pi conectado de %s", peer)
        while True:
            cab, dados = await asyncio.wait_for(protocolo.receberAsync(reader), 15)
            mid = cab.get("mesa")
            if not isinstance(mid, int):
                continue
            m = estado.mesa(mid)
            if cab["tipo"] == "status":
                m["status"] = cab
                m["recebido"] = time.time()
            elif cab["tipo"] == "quadro" and dados:
                m["jpeg"] = dados
                m["versao"] += 1
                async with estado.novoQuadro:
                    estado.novoQuadro.notify_all()
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ssl.SSLError,
            protocolo.ErroProtocolo, ValueError) as e:
        log.info("conexao do Pi %s encerrada (%s)", peer, type(e).__name__)
    finally:
        if estado.pi is writer:
            estado.pi = None
        writer.close()


async def enviarAoPi(cab):
    if estado.pi is None:
        return False
    estado.pi.write(protocolo.empacotar(cab))
    await estado.pi.drain()
    return True


# ---------------------------------------------------------------------------- web

def autorizado(cabecalhos, usuario, senha):
    valor = cabecalhos.get("authorization", "")
    if not valor.lower().startswith("basic "):
        return False
    try:
        u, _, s = base64.b64decode(valor[6:].strip()).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(u.encode(), usuario.encode()) & hmac.compare_digest(s.encode(), senha.encode())


def resposta(status, corpo=b"", tipo="text/plain; charset=utf-8", extra=""):
    if isinstance(corpo, str):
        corpo = corpo.encode("utf-8")
    cab = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
           "X-Content-Type-Options: nosniff\r\nConnection: close\r\n%s\r\n") % (status, tipo, len(corpo), extra)
    return cab.encode("ascii") + corpo


def statusJson():
    agora = time.time()
    mesas = {}
    for mid, m in sorted(estado.mesas.items()):
        st = dict(m["status"] or {})
        st.pop("tipo", None)
        st["idade_s"] = round(agora - m["recebido"], 1) if m["recebido"] else None
        mesas[str(mid)] = st
    return json.dumps({"pi_conectado": estado.pi is not None, "mesas": mesas})


async def transmitirVideo(writer, mid):
    fronteira = "quadro"
    writer.write(("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=%s\r\n"
                  "Cache-Control: no-store\r\nConnection: close\r\n\r\n" % fronteira).encode("ascii"))
    versao = -1
    while True:
        m = estado.mesas.get(mid)
        if m and m["jpeg"] and m["versao"] != versao:
            versao = m["versao"]
            jpeg = m["jpeg"]
            writer.write(("--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % (fronteira, len(jpeg))).encode("ascii"))
            writer.write(jpeg + b"\r\n")
            await writer.drain()
        async with estado.novoQuadro:
            try:
                await asyncio.wait_for(estado.novoQuadro.wait(), 5)
            except asyncio.TimeoutError:
                pass


async def atenderWeb(reader, writer, usuario, senha):
    try:
        linha = await asyncio.wait_for(reader.readline(), 10)
        partes = linha.decode("latin-1").split()
        if len(partes) != 3:
            return
        metodo, caminho, _ = partes
        cabecalhos = {}
        for _ in range(60):
            h = await asyncio.wait_for(reader.readline(), 10)
            if h in (b"\r\n", b"\n", b""):
                break
            k, _, v = h.decode("latin-1").partition(":")
            cabecalhos[k.strip().lower()] = v.strip()

        if not autorizado(cabecalhos, usuario, senha):
            writer.write(resposta("401 Unauthorized", "Acesso restrito",
                                  extra='WWW-Authenticate: Basic realm="Mesas de pinball", charset="UTF-8"\r\n'))
            return
        caminho = caminho.split("?")[0]
        if metodo == "GET" and caminho == "/":
            writer.write(resposta("200 OK", PAGINA, "text/html; charset=utf-8"))
        elif metodo == "GET" and caminho == "/status.json":
            writer.write(resposta("200 OK", statusJson(), "application/json"))
        elif metodo == "GET" and re.fullmatch(r"/video/\d+", caminho):
            await transmitirVideo(writer, int(caminho.rsplit("/", 1)[1]))
        elif metodo == "POST" and re.fullmatch(r"/zerar/\d+", caminho):
            # Cabecalho proprio: outro site nao consegue envia-lo sem permissao (protege contra CSRF)
            if cabecalhos.get("x-pinball") != "1":
                writer.write(resposta("403 Forbidden", "Requisicao recusada"))
                await writer.drain()
                return
            mid = int(caminho.rsplit("/", 1)[1])
            ok = mid in estado.mesas and await enviarAoPi({"tipo": "cmd", "mesa": mid, "c": "r"})
            writer.write(resposta("204 No Content") if ok else resposta("503 Service Unavailable", "Pi desconectado"))
        else:
            writer.write(resposta("404 Not Found", "Nao encontrado"))
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, ssl.SSLError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mesas de pinball</title>
<style>
:root{--bg:#14181b;--painel:#1d2327;--linha:#2f383e;--texto:#e3e8eb;--mut:#8d9aa2;--ok:#5fd08b;--alerta:#f0a35a;--erro:#f06a5a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--texto);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline;padding:14px 16px;border-bottom:1px solid var(--linha)}
h1{font-size:18px;margin:0;font-weight:600}
#pi{font-size:13px;color:var(--mut)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px;padding:16px}
section{background:var(--painel);border:1px solid var(--linha);border-radius:6px;overflow:hidden}
section img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:#000}
.info{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:center;padding:12px 14px}
.placar{font-size:34px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1}
.rot{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut)}
.val{font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.alerta{color:var(--alerta)}.erro{color:var(--erro)}
button{margin-left:auto;background:transparent;color:var(--texto);border:1px solid var(--linha);border-radius:4px;padding:8px 14px;font:inherit;cursor:pointer}
button:hover{border-color:var(--mut)}button:focus-visible{outline:2px solid var(--ok);outline-offset:2px}
</style></head><body>
<header><h1>Mesas de pinball</h1><span id="pi">Conectando…</span></header>
<main id="mesas"></main>
<script>
const cont=document.getElementById('mesas'), criadas={};
function painel(id){
  const s=document.createElement('section');
  s.innerHTML='<img alt="Vídeo da mesa '+id+'" src="/video/'+id+'">'+
    '<div class="info"><div><div class="rot">Mesa '+id+'</div><div class="placar" data-k="placar">–</div></div>'+
    '<div><div class="rot">Controle</div><div class="val" data-k="modo">–</div></div>'+
    '<div><div class="rot">Arduino</div><div class="val" data-k="arduino">–</div></div>'+
    '<div><div class="rot">Quadros/s</div><div class="val" data-k="fps">–</div></div>'+
    '<button type="button">Zerar placar</button></div>';
  s.querySelector('button').onclick=async e=>{
    const b=e.target;b.disabled=true;b.textContent='Zerando…';
    const r=await fetch('/zerar/'+id,{method:'POST',headers:{'X-Pinball':'1'}}).catch(()=>null);
    b.textContent=r&&r.ok?'Placar zerado':'Pi desconectado';
    setTimeout(()=>{b.disabled=false;b.textContent='Zerar placar'},1500);
  };
  cont.appendChild(s);return s;
}
function set(s,k,t,c){const el=s.querySelector('[data-k="'+k+'"]');el.textContent=t;el.className=(k==='placar'?'placar ':'val ')+(c||'')}
async function atualizar(){
  try{
    const d=await (await fetch('/status.json')).json();
    const pi=document.getElementById('pi');
    pi.textContent=d.pi_conectado?'Raspberry Pi conectado':'Raspberry Pi desconectado';
    pi.className=d.pi_conectado?'ok':'erro';
    for(const [id,m] of Object.entries(d.mesas)){
      const s=criadas[id]||(criadas[id]=painel(id));
      const a=m.arduino||{}, velho=m.idade_s==null||m.idade_s>3;
      set(s,'placar',a.total!=null?a.total:'–');
      set(s,'modo',m.modo==='ia'?'IA no PC'+(m.latencia_ms!=null?' · '+m.latencia_ms+' ms':''):(m.modo?'Math no Pi':'–'));
      set(s,'arduino',velho?'sem dados':(!a.serial?'desconectado':(a.conectado?(a.modo===1?'manual':'automático'):'sem resposta')),
          velho||!a.conectado?'erro':(a.modo===1?'alerta':'ok'));
      set(s,'fps',m.fps!=null?Math.round(m.fps):'–',m.camera===false?'erro':'');
    }
  }catch(e){const pi=document.getElementById('pi');pi.textContent='Servidor indisponível';pi.className='erro'}
}
atualizar();setInterval(atualizar,1000);
</script></body></html>"""


# ---------------------------------------------------------------------------- inicio

async def principal(args):
    global estado
    estado = Estado()
    tokenPi = os.environ.get("PINBALL_TOKEN_VM")
    usuario = os.environ.get("PINBALL_WEB_USUARIO")
    senha = os.environ.get("PINBALL_WEB_SENHA")
    if not tokenPi or not usuario or not senha:
        raise SystemExit("Defina PINBALL_TOKEN_VM, PINBALL_WEB_USUARIO e PINBALL_WEB_SENHA")

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(args.cert, args.chave)

    srvPi = await asyncio.start_server(lambda r, w: atenderPi(r, w, tokenPi), args.endereco, args.porta_pi, ssl=ctx)
    srvWeb = await asyncio.start_server(lambda r, w: atenderWeb(r, w, usuario, senha), args.endereco, args.porta_web, ssl=ctx)
    log.info("aguardando o Pi em %s:%d e a pagina web em https://%s:%d", args.endereco, args.porta_pi, args.endereco, args.porta_web)
    async with srvPi, srvWeb:
        await asyncio.gather(srvPi.serve_forever(), srvWeb.serve_forever())


def main():
    p = argparse.ArgumentParser(description="Servidor das mesas de pinball (VM)")
    p.add_argument("--cert", required=True, help="certificado TLS (PEM)")
    p.add_argument("--chave", required=True, help="chave privada do certificado (PEM)")
    p.add_argument("--endereco", default="0.0.0.0")
    p.add_argument("--porta-pi", type=int, default=8443)
    p.add_argument("--porta-web", type=int, default=8444)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    try:
        asyncio.run(principal(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
