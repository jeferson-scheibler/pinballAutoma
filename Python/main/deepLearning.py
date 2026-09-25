import os

import torch

# Classes do modelo best256pV9: {0: 'bola', 1: 'batedor'}
CLASSE_BOLA = 0

MODELO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "YoloModel", "best256pV9.onnx")


class deepLearning:
    def __init__(self, modelo=MODELO_PADRAO, tamanho=256, repo_local=None):
        """Carrega o modelo YOLOv5.

        modelo: caminho do .onnx/.pt (independe do diretorio de execucao).
        repo_local: caminho de um clone local do yolov5 para rodar sem internet;
                    se omitido, usa o torch.hub (baixa o repositorio na primeira execucao).
        """
        self.tamanho = tamanho
        modelo = os.path.abspath(modelo)
        if not os.path.isfile(modelo):
            raise FileNotFoundError("Modelo nao encontrado: " + modelo)
        if repo_local:
            self.model = torch.hub.load(repo_local, 'custom', modelo, source='local')
        else:
            self.model = torch.hub.load('ultralytics/yolov5', 'custom', modelo)

    def inference(self, image):
        """Retorna (x, y, raio) da bolinha com maior confianca, em pixels da imagem de entrada.

        Retorna (0, 0, 0) quando nenhuma bolinha e detectada.
        """
        results = self.model(image, size=self.tamanho)
        df = results.pandas().xywh[0]
        bolas = df[df["class"] == CLASSE_BOLA]
        if bolas.empty:
            return 0, 0, 0
        melhor = bolas.loc[bolas["confidence"].idxmax()]
        return int(melhor.xcenter), int(melhor.ycenter), float(melhor.width) / 2
