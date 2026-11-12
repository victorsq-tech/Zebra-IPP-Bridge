# Relatório de triagem da pasta enviada

**Fonte:** arquivo `ZebraIPP.zip` disponibilizado pelo usuário em 11/11/2026.

## Organização

A pasta enviada contém código-fonte atual, script de instalação, interface gráfica, executável preexistente, dependências instaladas e artefatos de execução. Para publicação, foi adotada uma **lista explícita de arquivos permitidos**, em vez de copiar a pasta inteira e depender apenas do `.gitignore`.

**Incluídos:** scripts Python atuais (servidor, formatador, ZPL, ponte RAW, GUI, verificadores), scripts BAT de instalação/build, requisitos, exemplos sintéticos, testes e documentação.

**Excluídos:** `.build-venv/` e bibliotecas de terceiros instaladas, `build/`, `dist/`, `__pycache__/`, `old/`, `copias/`, `Atualizacao/`, cópias de segurança (`ipp_server_backup.py`), prévias reais em `previews_ipp/` e documentos de testes com potencial de identificação. Isso reduz o ZIP e evita publicação de dados operacionais.

A pasta `Atualizacao/` contém versões byte a byte equivalentes às principais versões da raiz para os módulos avaliados (`ipp_server.py`, `zebra_fast_engine.py`, `zebra_formatter.py`). Portanto, não foi incorporada como segunda versão do software.

## Pontos de atenção para revisão de segurança

- O servidor recebe documentos em uma porta HTTP sem autenticação e TLS. Usar somente em rede confiável.
- O GUI aceita configurar o endereço de escuta e executar argumentos adicionais do servidor: usar apenas scripts conhecidos.
- O arquivo `print_pdf_zebra.py` **está incluído**, pois foi encontrado na raiz do ZIP enviado. Conferir `PRINTER` antes de imprimir.
- O repositório não inclui `.exe`: o executável Windows presente no arquivo original não foi executado ou auditado no ambiente de organização. Gere e teste um novo release no Windows.
- Não foi feita auditoria de segurança exaustiva, nem teste da Zebra física no ambiente de preparação do repositório.
