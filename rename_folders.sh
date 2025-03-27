#!/bin/bash

# Renomear pastas com espaços e caracteres especiais
mv "arquivos/Cidades de Atuação" "arquivos/cidades_de_atuacao" 2>/dev/null
mv "arquivos/Painel de Precificação" "arquivos/painel_de_precificacao" 2>/dev/null
mv "arquivos/Beneficiários" "arquivos/beneficiarios" 2>/dev/null
mv "arquivos/PrestadorasAcreditadas" "arquivos/prestadoras_acreditadas" 2>/dev/null
mv "arquivos/SIP" "arquivos/sip" 2>/dev/null
mv "arquivos/TUSS" "arquivos/tuss" 2>/dev/null
mv "arquivos/TaxaCobertura" "arquivos/taxa_cobertura" 2>/dev/null
mv "arquivos/Valores" "arquivos/valores" 2>/dev/null

echo "Renomeação concluída!"
