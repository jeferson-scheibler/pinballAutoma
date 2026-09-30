#!/bin/sh
# Hook de renovacao do certbot: copia o certificado do dominio para o servidor das mesas e o recarrega.
#
# Instalacao (como root):
#   install -m 755 certbot-deploy-hook-pinball.sh /etc/letsencrypt/renewal-hooks/deploy/pinball.sh
#   DOMINIO=dati.dev.br sh /etc/letsencrypt/renewal-hooks/deploy/pinball.sh   # copia agora, pela primeira vez
#
# O certbot define RENEWED_LINEAGE (ex.: /etc/letsencrypt/live/dati.dev.br) ao renovar.
# Se o certificado do dominio tiver outro nome em "certbot certificates", ajuste DOMINIO abaixo.
set -eu

DOMINIO="${DOMINIO:-dati.dev.br}"
ORIGEM="${RENEWED_LINEAGE:-/etc/letsencrypt/live/$DOMINIO}"
DESTINO=/etc/pinball/tls

# Quando chamado pelo certbot, so age no certificado do dominio
case "$ORIGEM" in
    */"$DOMINIO") ;;
    *) exit 0 ;;
esac

install -d -m 750 -o root -g pinball "$DESTINO"
install -m 644 -o root -g pinball "$ORIGEM/fullchain.pem" "$DESTINO/fullchain.pem"
install -m 640 -o root -g pinball "$ORIGEM/privkey.pem" "$DESTINO/privkey.pem"

# Recarrega o certificado sem derrubar a conexao do Pi (so se o servico ja estiver ativo)
if systemctl is-active --quiet pinball-vm; then
    systemctl reload pinball-vm
fi
