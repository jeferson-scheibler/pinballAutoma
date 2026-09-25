# Mesa de pinball autonoma
## Objetivo / Ideia
Esse foi um projeto desenvolvido pelo Laboratório de automação (Univates) em conjuto com o professor Alexandre Wolf.
A ideia é desenvolver duas mesas de pinball que podem jogar sozinhas, ou de forma manual. As duas mesas serão colocadas frente a frente, tendo o objetivo de lançar a bolinha para o outro lado e ir pontuando conforme a bolinha for batendo nos cantos. </br>
A automação da mesa será feita através de uma câmera apontada em direção a mesa que será responsavel por "enxergar" a bolinha e algumas marcações da mesa para localizar onde a bolinha se encontra, a area na qual os batedores atuam e a area de lançamento da bolinha. </br>
Para seu funcionamento autonomo se tem 2 formas de funcionamento:
- Algoritmo ("Math"): detecta a bolinha com HoughCircles (OpenCV) e a base dos batedores por uma marcação vermelha na mesa.
- IA ("Ai"): detecta a bolinha com um modelo YOLOv5 treinado (`Python/YoloModel/best256pV9`, classes `bola` e `batedor`).

Em ambos os modos a próxima posição da bolinha é extrapolada a partir dos últimos quadros; se ela cair na área de um batedor, o PC envia o comando para o Arduino.

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
python Python/main/main.py --porta COM3 --camera 0
```

Opções principais:
- `--porta` / `--baud`: porta serial do Arduino (ex.: `COM3`, `/dev/ttyACM0`)
- `--camera`: índice da câmera
- `--modo math|ai`: modo inicial (tecla `t` alterna durante a execução, `Esc` sai)
- `--lancador`: habilita o lançamento automático (requer a marcação azul do lançador)
- `--yolov5-local`: clone local do yolov5 para rodar o modo IA sem internet (por padrão o `torch.hub` baixa o repositório na primeira execução)
- `--sem-serial`: roda apenas a visão, sem Arduino

Protocolo serial (9600 baud), aceito somente no modo automático do Arduino:

| Comando | Ação |
|---|---|
| `1` | pulso no braço esquerdo |
| `2` | pulso no braço direito |
| `3` | pulso no lançador |

No Arduino, segurar os botões esquerdo e direito por 1 s alterna entre modo automático e manual. Por segurança, os solenoides acionados pelos botões desligam após 1,5 s mesmo com o botão pressionado (`MAX_ACIONADO_MS`).
