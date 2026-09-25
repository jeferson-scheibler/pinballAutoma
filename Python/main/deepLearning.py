"""Deteccao da bolinha com o modelo YOLOv5 exportado em ONNX.

Backends:
  opencv       (padrao) cv2.dnn; nao precisa de PyTorch nem de internet
  onnxruntime  opcional, se o pacote estiver instalado (pip install onnxruntime)
  torch        torch.hub + yolov5, para modelos .pt (baixa o repositorio na primeira execucao)
"""
import os

import cv2
import numpy

# Classes do modelo best256pV9: {0: 'bola', 1: 'batedor'}
CLASSE_BOLA = 0
CLASSE_BATEDOR = 1

MODELO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "YoloModel", "best256pV9.onnx")


def decodificarYolo(saida, conf_min, iou_max):
    """Decodifica a saida do YOLOv5 (N x [cx, cy, w, h, obj, cls0, cls1, ...]).

    Retorna uma lista de (classe, confianca, cx, cy, w, h) apos NMS por classe,
    em pixels da entrada da rede.
    """
    saida = numpy.asarray(saida).reshape(-1, saida.shape[-1])
    classes = numpy.argmax(saida[:, 5:], axis=1)
    conf = saida[:, 4] * saida[numpy.arange(len(saida)), 5 + classes]
    sel = conf >= conf_min
    saida, classes, conf = saida[sel], classes[sel], conf[sel]

    deteccoes = []
    for c in numpy.unique(classes):
        idx = numpy.where(classes == c)[0]
        caixas = [[float(cx - w / 2), float(cy - h / 2), float(w), float(h)]
                  for cx, cy, w, h in saida[idx, :4]]
        mantidos = cv2.dnn.NMSBoxes(caixas, conf[idx].tolist(), conf_min, iou_max)
        for k in numpy.array(mantidos).flatten():
            i = idx[int(k)]
            cx, cy, w, h = saida[i, :4]
            deteccoes.append((int(c), float(conf[i]), float(cx), float(cy), float(w), float(h)))
    deteccoes.sort(key=lambda d: d[1], reverse=True)
    return deteccoes


class deepLearning:
    def __init__(self, modelo=MODELO_PADRAO, tamanho=256, backend="opencv",
                 conf_min=0.25, iou_max=0.45, repo_local=None):
        self.tamanho = tamanho
        self.conf_min = conf_min
        self.iou_max = iou_max
        self.ultimasDeteccoes = []
        modelo = os.path.abspath(modelo)
        if not os.path.isfile(modelo):
            raise FileNotFoundError("Modelo nao encontrado: " + modelo)
        if backend == "torch" or modelo.endswith(".pt"):
            backend = "torch"
        self.backend = backend

        if backend == "opencv":
            self.net = cv2.dnn.readNetFromONNX(modelo)
        elif backend == "onnxruntime":
            import onnxruntime
            self.sessao = onnxruntime.InferenceSession(modelo, providers=["CPUExecutionProvider"])
            self.entrada = self.sessao.get_inputs()[0].name
        elif backend == "torch":
            import torch
            if repo_local:
                self.model = torch.hub.load(repo_local, 'custom', modelo, source='local')
            else:
                self.model = torch.hub.load('ultralytics/yolov5', 'custom', modelo)
            self.model.conf = conf_min
            self.model.iou = iou_max
        else:
            raise ValueError("Backend desconhecido: " + backend)
        print("Modelo carregado (%s): %s" % (backend, modelo))

    def _detectar(self, imageBGR):
        """Deteccoes em pixels da rede (tamanho x tamanho)."""
        entrada = cv2.resize(imageBGR, (self.tamanho, self.tamanho))
        if self.backend == "torch":
            df = self.model(cv2.cvtColor(entrada, cv2.COLOR_BGR2RGB), size=self.tamanho).pandas().xywh[0]
            return [(int(r["class"]), float(r.confidence), float(r.xcenter), float(r.ycenter),
                     float(r.width), float(r.height)) for _, r in df.iterrows()]

        blob = cv2.dnn.blobFromImage(entrada, 1 / 255.0, (self.tamanho, self.tamanho), swapRB=True)
        if self.backend == "opencv":
            self.net.setInput(blob)
            saida = self.net.forward()
        else:
            saida = self.sessao.run(None, {self.entrada: blob})[0]
        return decodificarYolo(saida, self.conf_min, self.iou_max)

    def inference(self, imageBGR):
        """Retorna (x, y, raio) da bolinha com maior confianca, em pixels da imagem recebida.

        Retorna (0, 0, 0) quando nenhuma bolinha e detectada. As deteccoes completas
        (incluindo os batedores) ficam em self.ultimasDeteccoes, ja na escala da imagem.
        """
        altura, largura = imageBGR.shape[:2]
        ex, ey = largura / self.tamanho, altura / self.tamanho
        self.ultimasDeteccoes = [(c, conf, cx * ex, cy * ey, w * ex, h * ey)
                                 for c, conf, cx, cy, w, h in self._detectar(imageBGR)]
        for c, conf, cx, cy, w, h in self.ultimasDeteccoes:
            if c == CLASSE_BOLA:
                return int(cx), int(cy), (w + h) / 4
        return 0, 0, 0
