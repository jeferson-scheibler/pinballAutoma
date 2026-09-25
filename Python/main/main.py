import argparse
import time

import cv2
import numpy
import serial

import config
from camera import abrirCamera, lerQuadro
from mesa import mesa
from perspectiva import Perspectiva
from rastreador import Rastreador
from traditional import traditional

# Comandos aceitos pelo Arduino
CMD_ESQUERDO = b'1'
CMD_DIREITO = b'2'
CMD_LANCAR = b'3'

TECLA_ESC = 27
TECLA_T = ord('t')


def parseArgs():
    p = argparse.ArgumentParser(description="Mesa de pinball autonoma")
    p.add_argument("--config", default=config.CAMINHO_PADRAO, help="arquivo de configuracao (gerado por calibracao.py)")
    p.add_argument("--porta", default="COM3", help="porta serial do Arduino (ex.: COM3, /dev/ttyACM0)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--camera", type=int, default=0, help="indice da camera")
    p.add_argument("--modo", choices=["math", "ai"], default="math", help="modo inicial de deteccao")
    p.add_argument("--modelo", default=None, help="caminho do modelo YOLO (.onnx/.pt)")
    p.add_argument("--yolov5-local", default=None, help="clone local do yolov5 (uso offline)")
    p.add_argument("--lancador", action="store_true",
                   help="habilita o lancamento automatico (requer a marcacao do lancador)")
    p.add_argument("--sem-serial", action="store_true", help="executa sem Arduino (apenas visualizacao)")
    return p.parse_args()


class Fps:
    def __init__(self):
        self.anterior = time.monotonic()

    def calc(self, agora):
        dt = agora - self.anterior
        self.anterior = agora
        return str(int(1 / dt)) if dt > 0 else "0"


def abrirSerial(args):
    if args.sem_serial:
        return None
    arduino = serial.Serial(args.porta, args.baud, timeout=0)
    # O Arduino reinicia ao abrir a porta; aguarda o bootloader antes de enviar comandos
    time.sleep(2)
    arduino.reset_input_buffer()
    return arduino


def enviar(arduino, comando):
    if arduino is not None:
        arduino.write(comando)


def retanguloMesa(persp, x, y, w, h):
    """Converte um retangulo da imagem para o retangulo envolvente em coordenadas da mesa."""
    pts = persp.paraMesa([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
    return float(x0), float(y0), float(x1 - x0), float(y1 - y0)


def desenharPoligono(image, persp, cantosMesa, cor):
    pts = persp.paraImagem(cantosMesa).astype(numpy.int32)
    cv2.polylines(image, [pts], True, cor, 1)


def pontoImagem(persp, x, y):
    px, py = persp.paraImagem([(x, y)])[0]
    return int(px), int(py)


def desenhar(image, persp, m, rast, modo, fpsTxt):
    font = cv2.FONT_HERSHEY_SIMPLEX

    if m.hb.valid:
        hb = m.hb
        desenharPoligono(image, persp, hb.cantos(), (0, 255, 0))
        desenharPoligono(image, persp, [(hb.x, hb.y), (hb.x, hb.y + hb.h)], (0, 255, 0))
    if m.lb.valid:
        desenharPoligono(image, persp, m.lb.cantos(), (255, 255, 0))

    for x, y in rast.trilha:
        cv2.circle(image, pontoImagem(persp, x, y), 1, (255, 0, 0), 2)

    if rast.valido:
        cv2.circle(image, pontoImagem(persp, *rast.posicao), 6, (0, 255, 0), 2)
        # Trajetoria prevista ate o instante em que o braco estaria em movimento
        traj = numpy.int32([pontoImagem(persp, x, y) for x, y in m.trajetoria(rast)])
        cv2.polylines(image, [traj], False, (255, 0, 255), 2)

    cv2.putText(image, 'Ai' if modo == 1 else 'Math', (0, 70), font, 1, (100, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(image, fpsTxt, (0, 45), font, 2, (100, 255, 0), 2, cv2.LINE_AA)


def main():
    args = parseArgs()
    cfg = config.carregar(args.config)
    cfgCam = cfg["camera"]

    captura = abrirCamera(args.camera, cfgCam)
    arduino = abrirSerial(args)
    persp = Perspectiva(cfg["perspectiva"])
    m = mesa(cfg)
    rast = Rastreador(cfg["previsao"])
    trad = traditional(cfg)
    deep = None
    modo = 1 if args.modo == "ai" else 0
    fps = Fps()

    def carregarDeep():
        from deepLearning import deepLearning, MODELO_PADRAO
        return deepLearning(args.modelo or MODELO_PADRAO, repo_local=args.yolov5_local)

    if modo == 1:
        deep = carregarDeep()

    try:
        while True:
            image = lerQuadro(captura, cfgCam)
            agora = time.monotonic()
            if image is None:
                print("Falha ao ler quadro da camera")
                break
            fpsTxt = fps.calc(agora)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # Marcacoes fisicas da mesa (usadas nos dois modos), em coordenadas da mesa
            bx, by = trad.findBase(image, hsv)
            if bx is not None:
                m.setposFlip(*persp.pontoMesa(bx, by))
            if args.lancador:
                lanc = trad.findLancador(image, hsv)
                if lanc is not None:
                    m.setposLancador(*retanguloMesa(persp, *lanc))

            if modo == 0:
                x, y, r = trad.detectCircle(image)
            else:
                imageRGB = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                imageRGB = cv2.resize(imageRGB, (deep.tamanho, deep.tamanho))
                x, y, r = deep.inference(imageRGB)
                x = x * cfgCam["largura"] / deep.tamanho
                y = y * cfgCam["altura"] / deep.tamanho

            rast.atualizar(persp.pontoMesa(x, y) if r > 0 else None, agora)

            hit, lado = m.isHit(rast, agora)
            if hit:
                enviar(arduino, CMD_DIREITO if lado == mesa.DIREITO else CMD_ESQUERDO)
            elif m.isLaunch(rast, agora):
                enviar(arduino, CMD_LANCAR)

            desenhar(image, persp, m, rast, modo, fpsTxt)
            cv2.imshow("Video", image)

            k = cv2.waitKey(1) & 0xff
            if k == TECLA_T:
                if modo == 0 and deep is None:
                    deep = carregarDeep()
                modo = 1 - modo
                rast.reiniciar()
            elif k == TECLA_ESC:
                break
    finally:
        captura.release()
        cv2.destroyAllWindows()
        if arduino is not None:
            arduino.close()


if __name__ == "__main__":
    main()
