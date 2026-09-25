# Mesa de pinball autonoma
## Objetivo / Ideia
Esse foi um projeto desenvolvido pelo Laboratório de automação (Univates) em conjuto com o professor Alexandre Wolf.
A ideia é desenvolver duas mesas de pinball que podem jogar sozinhas, ou de forma manual. As duas mesas serão colocadas frente a frente, tendo o objetivo de lançar a bolinha para o outro lado e ir pontuando conforme a bolinha for batendo nos cantos. </br>
A automação da mesa será feita através de uma câmera apontada em direção a mesa que será responsavel por "enxergar" a bolinha e algumas marcações da mesa para localizar onde a bolinha se encontra, a area na qual os batedores atuam e a area de lançamento da bolinha. </br>
Para seu funcionamento autonomo se tem 2 formas de funcionamento:
- Algoritmo ("Math"): detecta a bolinha com HoughCircles (OpenCV) e a base dos batedores por uma marcação colorida na mesa (vermelha por padrão, faixa HSV calibrável).
- IA ("Ai"): detecta a bolinha com um modelo YOLOv5 treinado (`Python/YoloModel/best256pV9.onnx`, classes `bola` e `batedor`), executado pelo OpenCV (sem PyTorch).

Em ambos os modos a bolinha é rastreada (filtro de Kalman) e, se a trajetória prevista chegar à área de um batedor dentro do tempo de reação do sistema, o PC envia o comando para o Arduino.

## Execução
### Mesa:
As mesas foram construidas toda em mdf e seus componentes eletronicos são (cada uma):
- 3 Push buttons com led, utilizado para os comandos
- 8 Botões de fim de curso, utilizado para capturar o impacto da bolinha em alguns cantos
- 3 Solenoides, utilizadas para os comandos do braço esquerdo, direito e lançamento da bolinha
- 1 módulo relé, utilizado para alimentar as solenoides
- 8 leds RGB
- 1 arduino mega, utilizado para controlar todos os componentes e se comunicar com o PC (explicação a frente)
- 1 Fonte de computador 400W+ utilizada para ambas as mesas
As mesas são espelhadas e identicas, todos os conectores e comandos serão iguais em ambos os lados

### Esquema eletrico/pinos
<p align="center">
  <img src="mapa%20pinball.png" width="600" />
</p>
As solenoides estão ligadas a um módulo relé que está sendo controlado pelo arduino

### Pc:

O PC será responsavel por controlar as mesas e utilizará comunicação serial para conversar com os arduinos.

### Automação:

O script principal fica em `Python/main/main.py`:

```bash
pip install -r Python/requirements.txt
python Python/main/calibracao.py --camera 0
python Python/main/main.py --porta COM3 --camera 0
```

#### Calibração (`calibracao.py`)
Todos os parâmetros ficam em `Python/main/config.json`, gerado pela ferramenta de calibração (tecla `s` salva). Modos:

| Tecla | Ajuste |
|---|---|
| `1` / `2` | faixa HSV da marcação da base dos batedores / do lançador (janela "Mascara" mostra o resultado) |
| `3` | detecção da bolinha (raios e parâmetros do HoughCircles) |
| `4` | tamanho da área dos batedores, latência e cooldown |
| `5` | exposição e balanço de branco da câmera (fixá-los deixa as cores estáveis) |
| `p` | marcar os 4 cantos da mesa (sup. esq., sup. dir., inf. dir., inf. esq.) para usar coordenadas da mesa |
| `c` | ativar/desativar a perspectiva |

Com a perspectiva ativa, as medidas da área dos batedores passam a ser em unidades da mesa (`largura_mesa` x `altura_mesa`, padrão 400 x 800), independentes da posição da câmera; reajuste-as no modo `4`.

#### Previsão e disparo
A bolinha é rastreada com um filtro de Kalman (posição e velocidade, usando o tempo real entre quadros). O batedor é acionado quando a trajetória prevista entra na área dos batedores dentro da `latencia_ms` (atraso entre o quadro e o braço em movimento), e o lado é definido pelo ponto de entrada. Para ajustar a latência: se o braço bate depois da bolinha passar, aumente; se bate cedo demais, diminua.

Opções principais do `main.py`:
- `--config`: arquivo de configuração (padrão `Python/main/config.json`)
- `--porta` / `--baud`: porta serial do Arduino (ex.: `COM3`, `/dev/ttyACM0`; padrão 115200 baud)
- `--camera`: índice da câmera
- `--modo math|ai`: modo inicial (tecla `t` alterna durante a execução, `r` zera o placar, `Esc` sai)
- `--lancador`: habilita o lançamento automático quando a bolinha está parada na área do lançador
- `--backend opencv|onnxruntime|torch`: execução do modelo no modo IA. O padrão `opencv` não precisa de PyTorch nem de internet; `onnxruntime` requer `pip install onnxruntime`; `torch` usa o `torch.hub` (para modelos `.pt`)
- `--yolov5-local`: clone local do yolov5 para o backend `torch` sem internet
- `--sem-serial`: roda apenas a visão, sem Arduino

#### Placar e comunicação com o Arduino
A tela mostra o modo do Arduino (automático/manual), o placar (total de impactos nos sensores) e o último sensor atingido. O PC pede o status a cada 1 s; se o Arduino não responder por 3 s, aparece **SEM RESPOSTA** em vermelho. No modo manual do Arduino o PC não envia comandos dos batedores.

Para duas mesas, rode uma instância por mesa, cada uma com sua câmera, porta e configuração (`--camera`, `--porta`, `--config`).

Protocolo serial (115200 baud):

| PC → Arduino | Ação |
|---|---|
| `1` / `2` / `3` | pulso no braço esquerdo / direito / lançador (somente no modo automático) |
| `?` | pede o status |
| `r` | zera o placar |

| Arduino → PC | Significado |
|---|---|
| `S,<modo>,<total>,<g0>,<g1>,<g2>,<g3>` | status: modo (0 automático, 1 manual), placar total e nível de cor de cada grupo de LEDs; enviado no início, após `?`, `r` e troca de modo |
| `H,<sensor>,<total>` | sensor de impacto atingido e placar atualizado |

No Arduino, segurar os botões esquerdo e direito por 1 s alterna entre modo automático e manual. Por segurança, os solenoides acionados pelos botões desligam após 1,5 s mesmo com o botão pressionado (`MAX_ACIONADO_MS`).
