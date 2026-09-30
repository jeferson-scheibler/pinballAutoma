# Configurar o servidor das mesas de pinball na VM do domínio `dati.dev.br`

Este documento é um roteiro **autossuficiente** para quem for configurar a VM (uma pessoa ou um
assistente com acesso SSH). Não pressupõe nenhum conhecimento prévio do projeto.

## 1. O que vamos instalar

O projeto é uma mesa de pinball autônoma (Laboratório de Automação da Univates). Um Raspberry Pi no
laboratório controla as mesas e **envia** para esta VM o placar, o status e um vídeo reduzido. A VM
mostra isso numa página web protegida por senha.

Repositório: <https://github.com/jeferson-scheibler/pinballAutoma> (branch `main`).
O servidor é um único arquivo Python que usa só a biblioteca padrão: `Python/main/servidor_vm.py`.

Resultado esperado:

| O que | Endereço | Quem acessa |
|---|---|---|
| Página com vídeo e placar | `https://dati.dev.br/mesa-pinball/` (via nginx, na porta 443) | pessoas, com usuário e senha |
| Conexão do Raspberry Pi | `dati.dev.br:8443` (TLS, com o certificado do domínio) | somente o Pi, com token |
| Servidor da página (interno) | `http://127.0.0.1:8444` | somente o nginx, nunca exposto |

Observações de projeto:
- A página fica em **um caminho** (`/mesa-pinball/`), não em um subdomínio. Ela usa endereços relativos,
  então funciona nesse caminho.
- A conexão do Pi **não é HTTP**; por isso usa uma porta própria (8443) e não passa pelo nginx.
- A VM **nunca aciona** as mesas. O único comando que ela repassa ao Pi é "zerar placar".

## 2. Regras de segurança para quem executar

Esta VM provavelmente hospeda **outros sites e serviços**. Siga à risca:

1. **Não altere nada além do descrito aqui.** Não mexa em outros `server {}` do nginx, em outros serviços,
   em regras de firewall existentes nem no certificado de outros domínios.
2. **Faça backup antes de editar** qualquer arquivo existente (por exemplo `sudo cp -a arquivo arquivo.bak-AAAAMMDD`).
3. **Valide antes de aplicar:** `sudo nginx -t` antes de todo `reload`. Use `reload`, nunca `restart`, no nginx.
4. **Não use `root` para rodar o servidor**; o serviço roda como o usuário `pinball` (sem login).
5. **Segredos:** gere o token e a senha na própria VM, grave só em `/etc/pinball/vm.env` (permissão 640) e
   mostre ao usuário **uma única vez**, no terminal, para ele levar ao Pi. Não os coloque no git, em logs,
   em issues nem em mensagens de commit.
6. **Peça confirmação ao usuário** antes de: abrir portas no firewall, editar o nginx, criar usuários.
7. Se algo não bater com este roteiro (sistema diferente, nginx com outra estrutura, outro gerenciador de
   certificados), **pare e pergunte** em vez de improvisar.

## 3. Passo 0: levantamento (somente leitura)

Antes de mudar qualquer coisa, colete e mostre ao usuário:

```bash
cat /etc/os-release | head -3
python3 --version                      # precisa ser 3.8 ou mais novo
nginx -v
sudo nginx -T 2>/dev/null | grep -nE "server_name|listen|ssl_certificate|location /mesa-pinball"
sudo certbot certificates              # nome do certificado e caminho; confirme que cobre dati.dev.br
sudo ss -ltnp | grep -E ":(8443|8444)\b" || echo "8443 e 8444 livres"
sudo ufw status verbose 2>/dev/null || sudo iptables -S 2>/dev/null | head -20
systemctl is-active pinball-vm 2>/dev/null || echo "servico ainda nao existe"
```

Confirme:
- `dati.dev.br` já resolve para esta VM e existe um `server { listen 443 ssl; server_name dati.dev.br; ... }`.
- Não existe um `location /mesa-pinball` (evitar conflito).
- As portas 8443 e 8444 estão livres.
- O certificado do domínio é gerenciado pelo **certbot**. Se for outro sistema (Caddy, acme.sh, certificado
  manual, painel do provedor), adapte o passo 4 e avise o usuário.

## 4. Passo 1: usuário e código

```bash
sudo useradd --system --home-dir /opt/mesaPinball --shell /usr/sbin/nologin pinball
sudo git clone https://github.com/jeferson-scheibler/pinballAutoma.git /opt/mesaPinball
sudo chown -R root:root /opt/mesaPinball          # o serviço só precisa ler
sudo install -d -m 750 -o root -g pinball /etc/pinball
```

Se o repositório for **privado**, peça ao usuário um jeito de acesso somente leitura (chave de deploy do
GitHub). Não peça senha nem token pessoal no chat.

Teste rápido de que o código roda: `python3 /opt/mesaPinball/Python/main/servidor_vm.py --help`.

## 5. Passo 2: certificado para a porta do Pi

O Pi valida o servidor pelo certificado do domínio, então **não é preciso** copiar nenhum `.crt` para o Pi.
O certbot guarda o certificado com acesso só do root; este hook copia para um lugar que o usuário `pinball`
lê e recarrega o serviço a cada renovação.

```bash
sudo install -m 755 /opt/mesaPinball/deploy/certbot-deploy-hook-pinball.sh /etc/letsencrypt/renewal-hooks/deploy/pinball.sh
sudo DOMINIO=dati.dev.br /etc/letsencrypt/renewal-hooks/deploy/pinball.sh     # primeira copia
ls -l /etc/pinball/tls                                                        # fullchain.pem (644) e privkey.pem (640)
```

Se o nome do certificado em `certbot certificates` não for `dati.dev.br` (por exemplo, um curinga), ajuste a
variável `DOMINIO` no script para o nome da pasta em `/etc/letsencrypt/live/`.

## 6. Passo 3: segredos

```bash
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
read -rsp "Senha da pagina web: " SENHA; echo
sudo tee /etc/pinball/vm.env >/dev/null <<EOF
PINBALL_TOKEN_VM=$TOKEN
PINBALL_WEB_USUARIO=lab
PINBALL_WEB_SENHA=$SENHA
EOF
sudo chown root:pinball /etc/pinball/vm.env && sudo chmod 640 /etc/pinball/vm.env
echo "Token do Pi (anote agora; ele vai em /etc/pinball/pi.env no Raspberry Pi): $TOKEN"
unset TOKEN SENHA
```

Escolha uma senha forte (o usuário pode trocar `lab` por outro nome). Depois de mostrar o token ao usuário,
não o repita.

## 7. Passo 4: serviço

```bash
sudo cp /opt/mesaPinball/deploy/pinball-vm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pinball-vm
systemctl status pinball-vm --no-pager
journalctl -u pinball-vm -n 20 --no-pager
```

O log deve mostrar: `aguardando o Pi em 0.0.0.0:8443 e a pagina web em http://127.0.0.1:8444`.

## 8. Passo 5: nginx

O trecho pronto está em `/opt/mesaPinball/deploy/nginx-mesa-pinball.conf`. Cole os dois blocos `location`
**dentro do `server {}` HTTPS de `dati.dev.br`** (com backup antes) e valide:

```bash
sudo cp -a /etc/nginx/sites-available/ARQUIVO-DO-DOMINIO /etc/nginx/sites-available/ARQUIVO-DO-DOMINIO.bak-$(date +%Y%m%d)
sudoedit /etc/nginx/sites-available/ARQUIVO-DO-DOMINIO      # cole os blocos dentro do server 443
sudo nginx -t && sudo systemctl reload nginx
```

Pontos que não podem mudar:
- `proxy_pass http://127.0.0.1:8444/;` **com a barra final** (remove o prefixo `/mesa-pinball/`).
- `proxy_buffering off;` (o vídeo é um fluxo contínuo; com buffer ele não aparece).
- `proxy_set_header X-Real-IP $remote_addr;` (o servidor usa para bloquear IPs que erram a senha).

Se `nginx -t` falhar, **desfaça a edição** (restaure o `.bak`), não recarregue e informe o erro ao usuário.

## 9. Passo 6: firewall

Somente a porta **8443** precisa ser aberta (a 443 já está aberta para o nginx). **Não abra a 8444.**

Pergunte ao usuário o IP público de saída do laboratório da Univates:
- **Se for fixo (recomendado):** libere só para ele.
  ```bash
  sudo ufw allow from IP_DO_LABORATORIO to any port 8443 proto tcp
  ```
- **Se não for fixo:** `sudo ufw allow 8443/tcp`. O servidor exige TLS e um token de 256 bits e bloqueia por
  10 minutos os IPs que erram o token 8 vezes, mas restringir por IP é bem mais seguro.

Se o firewall for de outro tipo (iptables puro, nftables, grupo de segurança do provedor da VM/nuvem, firewall
da universidade), faça o equivalente ou avise o usuário do que precisa ser liberado (TCP 8443, entrada).

## 10. Passo 7: verificação

```bash
# 1) portas em escuta: 8444 só em 127.0.0.1; 8443 em 0.0.0.0
sudo ss -ltnp | grep -E ":(8443|8444)\b"

# 2) pagina pelo nginx (peça a senha sem deixá-la no historico)
read -rsp "Senha: " SENHA; echo
curl -s -o /dev/null -w "sem senha: %{http_code}\n" https://dati.dev.br/mesa-pinball/
curl -s -o /dev/null -w "com senha: %{http_code}\n" -u "lab:$SENHA" https://dati.dev.br/mesa-pinball/
curl -s -u "lab:$SENHA" https://dati.dev.br/mesa-pinball/status.json ; echo
curl -sI https://dati.dev.br/mesa-pinball | head -3      # deve redirecionar (301) para /mesa-pinball/
unset SENHA

# 3) certificado da porta do Pi (de outra maquina, se possivel)
openssl s_client -connect dati.dev.br:8443 -servername dati.dev.br </dev/null 2>/dev/null | openssl x509 -noout -subject -dates
```

Esperado: `401` sem senha, `200` com senha, `status.json` com `"pi_conectado": false` enquanto o Pi não
conectar, e o certificado de `dati.dev.br` com validade em dia. Confirme também que os **outros sites** do
domínio continuam respondendo como antes.

## 11. Passo 8: lado do Raspberry Pi (o usuário faz depois)

No Pi, em `Python/main/pi.json` (a partir de `pi.exemplo.json`), a seção `vm` deve ficar:

```json
"vm": {"host": "dati.dev.br", "porta": 8443, "token_env": "PINBALL_TOKEN_VM",
       "ca": null, "nome_servidor": null, "fps": 10, "largura": 640, "jpeg_qualidade": 70}
```

E em `/etc/pinball/pi.env` do Pi: `PINBALL_TOKEN_VM=<o token gerado no passo 3>`.
Com o Pi conectado, o log da VM mostra `Pi conectado de ...` e a página passa a exibir o vídeo e o placar.

## 12. Operação e problemas comuns

| Sintoma | Causa provável e ação |
|---|---|
| Página abre mas o vídeo não aparece | falta `proxy_buffering off;` no nginx, ou o Pi ainda não conectou |
| Página em branco / erros 404 nos arquivos | `proxy_pass` sem a barra final, ou a URL aberta sem a barra (`/mesa-pinball`) |
| Log: `conexao recusada ... token invalido` | token do Pi diferente do `vm.env` |
| Log: `IP ... bloqueado por 600 s` | muitas tentativas erradas; `sudo systemctl restart pinball-vm` limpa o bloqueio |
| Pi: erro de certificado | o certificado da porta 8443 não é o do domínio, ou o hook não copiou (`ls -l /etc/pinball/tls`) |
| Pi não conecta | porta 8443 bloqueada em algum firewall; teste do Pi com `nc -vz dati.dev.br 8443` |
| Após renovar o certificado, o Pi cai | o hook deveria usar `reload` (não derruba); confira `journalctl -u pinball-vm` |

Comandos úteis: `journalctl -u pinball-vm -f` (log ao vivo), `sudo systemctl reload pinball-vm`
(recarrega o certificado), `sudo systemctl restart pinball-vm` (reinicia e limpa bloqueios).

**Atualizar o código:** `sudo git -C /opt/mesaPinball pull && sudo systemctl restart pinball-vm`.

**Desfazer tudo:**
```bash
sudo systemctl disable --now pinball-vm && sudo rm /etc/systemd/system/pinball-vm.service
sudo rm /etc/letsencrypt/renewal-hooks/deploy/pinball.sh
sudo rm -rf /etc/pinball /opt/mesaPinball && sudo userdel pinball
# restaure o arquivo do nginx a partir do .bak, rode "sudo nginx -t && sudo systemctl reload nginx"
# e remova a regra do firewall: sudo ufw delete allow 8443/tcp   (ou a regra por IP)
```

## 13. O que informar ao usuário no final

- Que passos foram executados e o resultado de cada verificação da seção 10.
- A regra de firewall criada (e se é restrita por IP).
- Onde estão o token e a senha (`/etc/pinball/vm.env`), sem repeti-los.
- Qualquer desvio deste roteiro e o motivo.
