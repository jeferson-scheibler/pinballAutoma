import argparse
import os
import time

import cv2

import config
from arduino import Arduino, MODO_MANUAL
from camera import abrirCamera, lerQuadro
from controle import ControleMesa
from desenho import desenharPlacar

TECLA_ESC = 27
TECLA_T = ord('t')
TECLA_R = ord('r')


def parseArgs():
    p = argparse.ArgumentParser(description="Mesa de pinball autonoma")
    p.add_argument("--config", default=None,
                   help="arquivo de configuracao (padrao: config.json local, ou a configuracao enviada pelo Pi com --pi)")
    p.add_argument("--porta", default="COM3", help="porta serial do Arduino (ex.: COM3, /dev/ttyACM0)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--camera", default="0", help="indice ou caminho da camera")
    p.add_argument("--modo", choices=["math", "ai"], default="math", help="modo inicial de deteccao")
    p.add_argument("--modelo", default=None, help="caminho do modelo YOLO (.onnx/.pt)")
    p.add_argument("--backend", choices=["opencv", "onnxruntime", "torch"], default="opencv",
                   help="execucao do modelo no modo IA (padrao: opencv, sem PyTorch)")
    p.add_argument("--yolov5-local", default=None, help="clone local do yolov5 (backend torch offline)")
    p.add_argument("--lancador", action="store_true",
                   help="habilita o lancamento automatico (requer a marcacao do lancador)")
    p.add_argument("--sem-serial", action="store_true", help="executa sem Arduino (apenas visualizacao)")
    p.add_argument("--pi", default=None, metavar="HOST[:PORTA]",
                   help="controla uma mesa pela rede: recebe as imagens do Raspberry Pi e envia os comandos a ele")
    p.add_argument("--mesa", type=int, default=1, help="numero da mesa no Pi (com --pi)")
    p.add_argument("--token", default=os.environ.get("PINBALL_TOKEN_LAN"),
                   help="token de acesso ao Pi (padrao: variavel PINBALL_TOKEN_LAN)")
    p.add_argument("--latencia-ms", type=int, default=None,
                   help="sobrescreve previsao.latencia_ms (com --pi, some o atraso da rede)")
    return p.parse_args()


class Fps:
    def __init__(self):
        self.anterior = None

    def calc(self, agora):
        dt = agora - self.anterior if self.anterior is not None else 0
        self.anterior = agora
        return str(int(1 / dt)) if dt > 0 else "0"


def main():
    args = parseArgs()
    conexao = None
    if args.pi:
        if not args.token:
            raise SystemExit("Informe o token do Pi com --token ou PINBALL_TOKEN_LAN")
        from rede import ConexaoPi
        conexao = ConexaoPi(args.pi, args.token, args.mesa)
        cfg = config.carregar(args.config) if args.config else conexao.config
        captura, arduino = conexao.camera, conexao.arduino
        print("Controlando a mesa %d pelo Pi %s" % (args.mesa, args.pi))
    else:
        cfg = config.carregar(args.config or config.CAMINHO_PADRAO)
        camera = int(args.camera) if args.camera.isdigit() else args.camera
        captura = abrirCamera(camera, cfg["camera"])
        arduino = Arduino(None if args.sem_serial else args.porta, args.baud)
    if args.latencia_ms is not None:
        cfg["previsao"]["latencia_ms"] = args.latencia_ms

    ctrl = ControleMesa(cfg, lancador=args.lancador)
    deep = None
    modo = 1 if args.modo == "ai" else 0
    fps = Fps()

    def carregarDeep():
        from deepLearning import deepLearning, MODELO_PADRAO
        return deepLearning(args.modelo or MODELO_PADRAO, backend=args.backend,
                            repo_local=args.yolov5_local)

    if modo == 1:
        deep = carregarDeep()

    try:
        while True:
            if conexao:
                # Instantes no relogio do Pi (captura do quadro)
                image, agora = captura.ler()
                if image is None:
                    if not conexao.ativa:
                        print("Conexao com o Pi perdida")
                        break
                    continue
                arduino.usarQuadro(agora)
            else:
                image = lerQuadro(captura, cfg["camera"])
                agora = time.monotonic()
                if image is None:
                    print("Falha ao ler quadro da camera")
                    break
            fpsTxt = fps.calc(agora)

            deteccao = deep.inference(image) if modo == 1 else None
            arduino.atualizar(agora)
            # No modo manual do Arduino os comandos seriam ignorados; nao gasta o cooldown
            for comando in ctrl.processar(image, agora, deteccao, permitirDisparo=arduino.modo != MODO_MANUAL):
                arduino.enviar(comando)

            ctrl.desenhar(image, 'Ai' if modo == 1 else 'Math', fpsTxt)
            desenharPlacar(image, arduino, agora)
            cv2.imshow("Video", image)

            k = cv2.waitKey(1) & 0xff
            if k == TECLA_T:
                if modo == 0 and deep is None:
                    deep = carregarDeep()
                modo = 1 - modo
                ctrl.reiniciar()
            elif k == TECLA_R:
                arduino.zerarPlacar()
            elif k == TECLA_ESC:
                break
    finally:
        captura.release()
        cv2.destroyAllWindows()
        arduino.fechar()


if __name__ == "__main__":
    main()
