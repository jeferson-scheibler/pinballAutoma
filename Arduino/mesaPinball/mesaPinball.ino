// Protocolo serial (115200 baud, linhas terminadas em '\n')
//
// PC -> Arduino (1 caractere):
//   '1' pulso no braco esquerdo    '2' pulso no braco direito    '3' pulso no lancador
//       (os tres so sao aceitos no modo automatico)
//   '?' pede o status              'r' zera o placar
//
// Arduino -> PC:
//   S,<modo>,<total>,<g0>,<g1>,<g2>,<g3>   status (no inicio, apos '?', 'r' e troca de modo)
//   H,<sensor>,<total>                    sensor de impacto atingido
//   modo: 0 = automatico, 1 = manual; g0..g3 = nivel de cor de cada grupo de leds (0-4)

//Matriz que relaciona o numero do led(1..8) com os pinos R, G, B conectados ao arduino
int leds[8][3] = {
  {32, 53, 30},
  {34, 40, 48},
  {38, 44, 51},
  {36, 42, 52},
  {37, 45, 46},
  {39, 43, 49},
  {41, 47, 50},
  {33, 35, 31}
};

//Utilizado somente para criar o efeito de onda inicial
int wave[4][2] = {
  {4, 5},
  {3, 6},
  {2, 7},
  {1, 8}
};

//Pinos dos botoes de fim de curso (sensores de impacto)
int btns[] = {29, 23, 25, 24, 26, 22, 28, 27};
const int N_SENSORES = 8;

//Separa os botões em grupos sendo a posição 1 representado pelo led 1 e a posição 2 pelos leds 2,3 e 4
int controlaEstados[] = {0, 0, 0, 0};
const int PONTUACAO_MAX = 4;

//Botoes de comando
int commandBtns[] = {3, 2, 4}; //3 = direito, 2 = esquerdo, 4 = launch

const int MODO_AUTOMATICO = 0;
const int MODO_MANUAL = 1;
int gameMode = MODO_AUTOMATICO;

// Tempos (ms)
const unsigned long PULSO_MS = 200;          // pulso do solenoide no modo automatico
const unsigned long MAX_ACIONADO_MS = 1500;  // tempo maximo com o solenoide energizado pelo botao
const unsigned long DEBOUNCE_MS = 30;        // filtro dos sensores de impacto
const unsigned long TROCA_MODO_MS = 1000;    // tempo segurando os dois botoes para trocar de modo

const long BAUD = 115200;

// Pontuacao total (numero de impactos nos sensores)
unsigned long pontosTotal = 0;

// Solenoides (rele ativo em LOW)
struct Solenoide {
  int pino;
  bool ativo;
  bool porBotao;        // acionado pelo botao (desliga ao soltar) ou por pulso
  bool bloqueado;       // atingiu o tempo maximo; so rearma ao soltar o botao
  unsigned long inicio;
  unsigned long duracao;
};

Solenoide esq = {7, false, false, false, 0, 0};    // braço esquerdo
Solenoide dir = {6, false, false, false, 0, 0};    // braço direito
Solenoide launch = {5, false, false, false, 0, 0}; // lancador

// Prototipos explicitos: o gerador automatico da IDE pode declara-los antes do struct
void ligaSolenoide(Solenoide &s, unsigned long duracao, bool porBotao);
void desligaSolenoide(Solenoide &s);
void atualizaSolenoide(Solenoide &s, unsigned long agora);
void pulsoSolenoide(Solenoide &s);
void controlaPorBotao(Solenoide &s, int pinoBtn, unsigned long agora);

// Debounce dos sensores
int sensorLeitura[N_SENSORES];
int sensorEstavel[N_SENSORES];
unsigned long sensorMudanca[N_SENSORES];

// Troca de modo
unsigned long inicioTrocaModo = 0;
bool trocaModoArmada = true;

// Animacoes (nao bloqueantes)
enum Animacao { ANIM_NENHUMA, ANIM_ONDA, ANIM_PISCA };
Animacao animAtual = ANIM_NENHUMA;
int animQuadro = 0;
bool animPiscaDepois = false;
unsigned long animProximo = 0;


void setup()
{
  Serial.begin(BAUD);

  desligaSolenoide(esq);
  desligaSolenoide(dir);
  desligaSolenoide(launch);
  pinMode(esq.pino, OUTPUT);
  pinMode(dir.pino, OUTPUT);
  pinMode(launch.pino, OUTPUT);

  // Definindo todos pinos como output
  for (int i = 0; i < 8; i++) {
    for (int j = 0; j < 3; j++) {
      pinMode(leds[i][j], OUTPUT);
    }
  }
  apagaLeds();

  // Definindo botões como pullup
  for (int i = 0; i < N_SENSORES; i++) {
    pinMode(btns[i], INPUT_PULLUP);
    sensorLeitura[i] = HIGH;
    sensorEstavel[i] = HIGH;
    sensorMudanca[i] = 0;
  }

  for (int i = 0; i < 3; i++) {
    pinMode(commandBtns[i], INPUT_PULLUP);
  }

  randomSeed(analogRead(A0));
  reset();
  iniciaAnimacao(true);
  enviaStatus();
}

// Nenhuma rotina do loop usa delay(): comandos seriais e botoes sao
// atendidos a cada iteracao, mesmo durante animacoes e pulsos.
void loop()
{
  unsigned long agora = millis();

  leBtnMode(agora);
  leSerial();

  if (gameMode == MODO_MANUAL) {
    controlaPorBotao(dir, commandBtns[0], agora);
    controlaPorBotao(esq, commandBtns[1], agora);
  }
  controlaPorBotao(launch, commandBtns[2], agora);

  atualizaSolenoide(esq, agora);
  atualizaSolenoide(dir, agora);
  atualizaSolenoide(launch, agora);

  lePin(agora);
  atualizaAnimacao(agora);
}

void reset() {
  desligaSolenoide(esq);
  desligaSolenoide(dir);
  desligaSolenoide(launch);
  zeraPlacar();
}

void zeraPlacar() {
  for (int i = 0; i < 4; i++) {
    controlaEstados[i] = 0;
  }
  pontosTotal = 0;
}

// ---------------------------------------------------------------- Solenoides

void ligaSolenoide(Solenoide &s, unsigned long duracao, bool porBotao) {
  s.ativo = true;
  s.porBotao = porBotao;
  s.inicio = millis();
  s.duracao = duracao;
  digitalWrite(s.pino, LOW);
}

void desligaSolenoide(Solenoide &s) {
  s.ativo = false;
  s.porBotao = false;
  digitalWrite(s.pino, HIGH);
}

// Desliga o solenoide ao fim do pulso ou ao atingir o tempo maximo acionado
void atualizaSolenoide(Solenoide &s, unsigned long agora) {
  if (s.ativo && agora - s.inicio >= s.duracao) {
    if (s.porBotao) {
      s.bloqueado = true;
    }
    desligaSolenoide(s);
  }
}

// Pulso vindo do PC. Ignorado se o solenoide ja estiver acionado.
void pulsoSolenoide(Solenoide &s) {
  if (!s.ativo) {
    ligaSolenoide(s, PULSO_MS, false);
  }
}

// Mantem o solenoide acionado enquanto o botao estiver pressionado,
// limitado a MAX_ACIONADO_MS para nao superaquecer a bobina.
void controlaPorBotao(Solenoide &s, int pinoBtn, unsigned long agora) {
  if (digitalRead(pinoBtn) == LOW) {
    if (!s.ativo && !s.bloqueado) {
      ligaSolenoide(s, MAX_ACIONADO_MS, true);
    }
  } else {
    s.bloqueado = false;
    if (s.ativo && s.porBotao) {
      desligaSolenoide(s);
    }
  }
}

// ---------------------------------------------------------------- Comandos

void leSerial() {
  while (Serial.available() > 0) {
    char leitura = Serial.read();
    if (leitura == '?') {
      enviaStatus();
      continue;
    }
    if (leitura == 'r') {
      zeraPlacar();
      if (animAtual == ANIM_NENHUMA) {
        apagaLeds();
      }
      enviaStatus();
      continue;
    }
    if (gameMode != MODO_AUTOMATICO) {
      continue;
    }
    if (leitura == '1') {
      pulsoSolenoide(esq);
    } else if (leitura == '2') {
      pulsoSolenoide(dir);
    } else if (leitura == '3') {
      pulsoSolenoide(launch);
    }
  }
}

// Segurar direito + esquerdo por TROCA_MODO_MS alterna entre automatico e manual.
// E preciso soltar os botoes antes de uma nova troca.
void leBtnMode(unsigned long agora) {
  bool ambos = digitalRead(commandBtns[0]) == LOW && digitalRead(commandBtns[1]) == LOW;
  if (!ambos) {
    inicioTrocaModo = 0;
    trocaModoArmada = true;
    return;
  }
  if (!trocaModoArmada) {
    return;
  }
  if (inicioTrocaModo == 0) {
    inicioTrocaModo = agora;
  } else if (agora - inicioTrocaModo > TROCA_MODO_MS) {
    gameMode = (gameMode == MODO_AUTOMATICO) ? MODO_MANUAL : MODO_AUTOMATICO;
    reset();
    // Exige soltar os botoes antes de acionar os bracos no novo modo
    esq.bloqueado = true;
    dir.bloqueado = true;
    trocaModoArmada = false;
    inicioTrocaModo = 0;
    iniciaAnimacao(false);
    enviaStatus();
  }
}

void enviaStatus() {
  Serial.print(F("S,"));
  Serial.print(gameMode);
  Serial.print(',');
  Serial.print(pontosTotal);
  for (int i = 0; i < 4; i++) {
    Serial.print(',');
    Serial.print(controlaEstados[i]);
  }
  Serial.print('\n');
}

// ---------------------------------------------------------------- Sensores / pontuacao

// Conta um ponto apenas na borda de descida (sensor pressionado), com debounce
void lePin(unsigned long agora) {
  for (int i = 0; i < N_SENSORES; i++) {
    int leitura = digitalRead(btns[i]);
    if (leitura != sensorLeitura[i]) {
      sensorLeitura[i] = leitura;
      sensorMudanca[i] = agora;
    }
    if (agora - sensorMudanca[i] >= DEBOUNCE_MS && leitura != sensorEstavel[i]) {
      sensorEstavel[i] = leitura;
      if (leitura == LOW) {
        btnHit(i);
      }
    }
  }
}

void btnHit(int btn) {
  int grupo;
  if (btn == 0) {
    grupo = 0;
  } else if (btn <= 3) {
    grupo = 1;
  } else if (btn <= 6) {
    grupo = 2;
  } else {
    grupo = 3;
  }
  // Cicla as cores: 1 -> 2 -> 3 -> 4 (branco) -> 1 ...
  controlaEstados[grupo] = (controlaEstados[grupo] % PONTUACAO_MAX) + 1;
  pontosTotal++;

  Serial.print(F("H,"));
  Serial.print(btn);
  Serial.print(',');
  Serial.print(pontosTotal);
  Serial.print('\n');
  if (animAtual == ANIM_NENHUMA) {
    atualizaLeds();
  }
}

// Cor de cada nivel de pontuacao: 1 = vermelho, 2 = verde, 3 = azul, 4 = branco
void corGrupo(int estado, int primeiroLed, int ultimoLed) {
  if (estado < 1 || estado > PONTUACAO_MAX) {
    return;
  }
  bool r = (estado == 1 || estado == 4);
  bool g = (estado == 2 || estado == 4);
  bool b = (estado == 3 || estado == 4);
  for (int n = primeiroLed; n <= ultimoLed; n++) {
    led(n, r, g, b);
  }
}

void atualizaLeds() {
  corGrupo(controlaEstados[0], 1, 1);
  corGrupo(controlaEstados[1], 2, 4);
  corGrupo(controlaEstados[2], 5, 7);
  corGrupo(controlaEstados[3], 8, 8);
}

// ---------------------------------------------------------------- LEDs / animacoes

void apagaLeds() {
  for (int i = 1; i <= 8; i++) {
    led(i, false, false, false);
  }
}

// Onda (5 ciclos de 8 quadros de 60 ms), opcionalmente seguida de pisca aleatorio
// (20 ciclos de 2 quadros de 50 ms)
void iniciaAnimacao(bool comPisca) {
  animAtual = ANIM_ONDA;
  animQuadro = 0;
  animPiscaDepois = comPisca;
  animProximo = millis();
  apagaLeds();
}

void finalizaAnimacao() {
  animAtual = ANIM_NENHUMA;
  apagaLeds();
  atualizaLeds();
}

void atualizaAnimacao(unsigned long agora) {
  if (animAtual == ANIM_NENHUMA || (long)(agora - animProximo) < 0) {
    return;
  }

  if (animAtual == ANIM_ONDA) {
    int passo = animQuadro % 8;
    bool acende = passo < 4;
    int par = passo % 4;
    for (int j = 0; j < 2; j++) {
      led(wave[par][j], acende, false, false);
    }
    animProximo = agora + 60;
    animQuadro++;
    if (animQuadro >= 5 * 8) {
      if (animPiscaDepois) {
        animAtual = ANIM_PISCA;
        animQuadro = 0;
      } else {
        finalizaAnimacao();
      }
    }
  } else {
    if (animQuadro % 2 == 0) {
      for (int i = 1; i <= 8; i++) {
        led(i, random(100) > 50, random(100) > 50, random(100) > 50);
      }
    } else {
      apagaLeds();
    }
    animProximo = agora + 50;
    animQuadro++;
    if (animQuadro >= 20 * 2) {
      finalizaAnimacao();
    }
  }
}

// nLed de 1 a 8. Os leds 2 a 7 sao de anodo comum (logica invertida).
void led(int nLed, boolean red, boolean green, boolean blue) {
  nLed = nLed - 1;
  if (nLed < 0 || nLed > 7) {
    return;
  }
  if (nLed >= 1 && nLed <= 6) {
    digitalWrite(leds[nLed][0], !red);
    digitalWrite(leds[nLed][1], !green);
    digitalWrite(leds[nLed][2], !blue);
  } else {
    digitalWrite(leds[nLed][0], red);
    digitalWrite(leds[nLed][1], green);
    digitalWrite(leds[nLed][2], blue);
  }
}
