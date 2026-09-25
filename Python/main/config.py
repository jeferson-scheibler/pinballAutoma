"""Configuracao da mesa, salva em JSON.

Todos os parametros de calibracao (cores, camera, perspectiva, previsao) ficam aqui,
para que possam ser ajustados pela ferramenta calibracao.py sem alterar o codigo.
"""
import copy
import json
import os

CAMINHO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

PADRAO = {
    "camera": {
        "largura": 800,
        "altura": 600,
        # Com exposicao/balanco automaticos a cor das marcacoes varia com a luz;
        # fixe-os pela calibracao quando possivel. Os valores dependem do driver.
        "exposicao_auto": True,
        "exposicao": -6,
        "balanco_branco_auto": True,
        "temperatura_branco": 4500,
    },
    # Faixas HSV do OpenCV (H: 0-179, S e V: 0-255).
    # Quando h_min > h_max a faixa "da a volta" no vermelho (ex.: 170..10).
    "cores": {
        "base": {"h_min": 170, "h_max": 10, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
        "lancador": {"h_min": 100, "h_max": 130, "s_min": 100, "s_max": 255, "v_min": 60, "v_max": 255},
    },
    "bolinha": {
        "raio_min": 10,
        "raio_max": 20,
        "param1": 100,
        "param2": 30,
        # Meia largura da regiao de busca em volta da posicao prevista (pixels da imagem)
        "roi_margem": 90,
    },
    # Transformacao para coordenadas da mesa. Os cantos sao pontos da imagem,
    # na ordem: superior esquerdo, superior direito, inferior direito, inferior esquerdo.
    "perspectiva": {
        "ativa": False,
        "cantos": [],
        "largura_mesa": 400,
        "altura_mesa": 800,
    },
    # Medidas em unidades da mesa (pixels da imagem quando a perspectiva esta desativada)
    "batedores": {
        "largura": 200,
        "altura": 100,
        "suavizacao_base": 0.2,
    },
    "lancador": {
        "ajuste": [15, 0, 40, 30],
        "velocidade_max": 40.0,
    },
    "previsao": {
        # Atraso total entre o quadro capturado e o braco em movimento
        # (camera + processamento + serial + rele + solenoide)
        "latencia_ms": 80,
        "cooldown_ms": 350,
        "cooldown_lancador_ms": 2000,
        # Filtro de Kalman: desvio padrao da aceleracao (unid/s^2; quanto maior, mais
        # rapido reage a batidas) e da medicao (unid; ruido da deteccao)
        "aceleracao_desvio": 1500.0,
        "medicao_desvio": 2.0,
        # Deteccao mais distante que isso da posicao prevista reinicia o rastreamento
        "salto_max": 150.0,
        "quadros_perdidos_max": 5,
    },
}


def _mesclar(base, novo):
    for chave, valor in novo.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            _mesclar(base[chave], valor)
        else:
            base[chave] = valor
    return base


def carregar(caminho=CAMINHO_PADRAO):
    """Carrega a configuracao. Chaves ausentes no arquivo recebem o valor padrao."""
    cfg = copy.deepcopy(PADRAO)
    if os.path.isfile(caminho):
        with open(caminho, encoding="utf-8") as f:
            _mesclar(cfg, json.load(f))
    return cfg


def salvar(cfg, caminho=CAMINHO_PADRAO):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
