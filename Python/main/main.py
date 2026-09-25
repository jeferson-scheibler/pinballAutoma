import argparse
import time

import cv2
import serial

from mesa import mesa
from traditional import traditional

LARGURA, ALTURA = 800, 600

# Comandos aceitos pelo Arduino
CMD_ESQUERDO = b'1'
CMD_DIREITO = b'2'
CMD_LANCAR = b'3'

TECLA_ESC = 27
TECLA_T = ord('t')


def parseArgs():
    p = argparse.ArgumentParser(description="Mesa de pinball autonoma")
    p.add_argument("--porta", default="COM3", help="porta serial do Arduino (ex.: COM3, /dev/ttyACM0)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--camera", type=int, default=0, help="indice da camera")
    p.add_argument("--modo", choices=["math", "ai"], default="math", help="modo inicial de deteccao")
    p.add_argument("--modelo", default=None, help="caminho do modelo YOLO (.onnx/.pt)")
    p.add_argument("--yolov5-local", default=None, help="clone local do yolov5 (uso offline)")
    p.add_argument("--lancador", action="store_true",
                   help="habilita o lancamento automatico (requer a marcacao azul do lancador)")
    p.add_argument("--sem-serial", action="store_true", help="executa sem Arduino (apenas visualizacao)")
    return p.parse_args()


class Fps:
    def __init__(self):
        self.anterior = time.monotonic()

    def calc(self):
        agora = time.monotonic()
        dt = agora - self.anterior
        self.anterior = agora
        return str(int(1 / dt)) if dt > 0 else "0"


def getImage(captura):
    ret, frame = captura.read()
    if not ret or frame is None:
        return None
    return cv2.resize(frame, (LARGURA, ALTURA))


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


def main():
    args = parseArgs()

    captura = cv2.VideoCapture(args.camera)
    if not captura.isOpened():
        raise SystemExit("Nao foi possivel abrir a camera %d" % args.camera)

    arduino = abrirSerial(args)
    m = mesa()
    trad = traditional()
    deep = None
    mode = 1 if args.modo == "ai" else 0
    fps = Fps()
    font = cv2.FONT_HERSHEY_SIMPLEX

    def carregarDeep():
        from deepLearning import deepLearning, MODELO_PADRAO
        return deepLearning(args.modelo or MODELO_PADRAO, repo_local=args.yolov5_local)

    if mode == 1:
        deep = carregarDeep()

    try:
        while True:
            image = getImage(captura)
            if image is None:
                print("Falha ao ler quadro da camera")
                break
            fpsTxt = fps.calc()

            # Marcacoes fisicas da mesa (usadas nos dois modos)
            m.setposFlip(*trad.findBase(image))
            if args.lancador:
                lanc = trad.findLancador(image)
                if lanc is not None:
                    m.setposLancador(*lanc)

            if mode == 0:
                x, y, r = trad.detectCircle(image)
            else:
                imageRGB = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                imageRGB = cv2.resize(imageRGB, (deep.tamanho, deep.tamanho))
                x, y, r = deep.inference(imageRGB)
                escalaX = LARGURA / deep.tamanho
                escalaY = ALTURA / deep.tamanho
                x, y, r = int(x * escalaX), int(y * escalaY), int(r * escalaX)
            m.setposBol(x, y, r)

            for i in range(len(m.bx)):
                if i == 0:
                    cv2.circle(image, (m.bx[i], m.by[i]), m.radio, (0, 255, 0), 2)
                cv2.circle(image, (m.bx[i], m.by[i]), 1, (255, 0, 0), 2)

            prevista = m.getnextPos(2)
            if prevista is not None:
                cv2.circle(image, prevista, 1, (255, 0, 255), 2)

            hit, lado = m.isHit()
            if hit:
                enviar(arduino, CMD_DIREITO if lado == mesa.DIREITO else CMD_ESQUERDO)
                # Evita reaproveitar a trajetoria antiga apos o acionamento
                m.clearHistory()
            elif m.isLaunch():
                enviar(arduino, CMD_LANCAR)
                m.clearHistory()

            if m.hb.valid:
                hb = m.hb
                cv2.rectangle(image, (hb.x, hb.y), (int(hb.x + hb.w / 2), hb.y + hb.h), (0, 255, 0), 1)
                cv2.rectangle(image, (int(hb.x - hb.w / 2), hb.y), (hb.x, hb.y + hb.h), (0, 255, 0), 1)
            if m.lb.valid:
                lb = m.lb
                cv2.rectangle(image, (lb.x, lb.y), (lb.x + lb.w, lb.y + lb.h), (255, 255, 0), 1)

            cv2.putText(image, 'Ai' if mode == 1 else 'Math', (0, 70), font, 1, (100, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(image, fpsTxt, (0, 45), font, 2, (100, 255, 0), 2, cv2.LINE_AA)
            cv2.imshow("Video", image)

            k = cv2.waitKey(1) & 0xff
            if k == TECLA_T:
                if mode == 0 and deep is None:
                    deep = carregarDeep()
                mode = 1 - mode
                m.clearHistory()
            elif k == TECLA_ESC:
                break
    finally:
        captura.release()
        cv2.destroyAllWindows()
        if arduino is not None:
            arduino.close()


if __name__ == "__main__":
    main()
