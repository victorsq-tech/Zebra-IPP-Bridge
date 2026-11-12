# Arquitetura do Zebra IPP Bridge

## Visão geral

```text
Android -> descoberta opcional por mDNS/DNS-SD -> HTTP POST /ipp/print
                                         |
                                         v
                               Handler / IPP parser
                                         |
                          Validação do tipo e dos limites
                                         |
                            Fila de trabalhos (worker)
                                         |
                        PDF (PyMuPDF) / imagens (Pillow)
                                         |
                           zebra_formatter.py (smart)
                                         |
                         Raster 480x879 e binarização
                                         |
                   zebra_fast_engine.py (ZPL ^GFA + lotes)
                                         |
                   print_pdf_zebra.send_raw (pywin32)
                                         |
                       Fila de impressão do Windows
                                         |
                         Zebra ZD220 USB / etiquetas
```

### Arquivos essenciais

- `ipp_server.py`: servidor HTTP multithread, interpretação IPP, fila de até 8 trabalhos por padrão, trabalhador único, medição de limites, gerenciamento básico de status, prévias e anúncio mDNS.
- `zebra_formatter.py`: recorte do conteúdo, orientação automática ou manual, margens, alinhamento, escala e renderização de PDF/imagem.
- `zebra_fast_engine.py`: perfil ZPL `ZebraProfile(width=480,length=879)`, raster binário, `^GFA` e opção de compressão Z64 **experimental**, `SpoolBatch`.
- `print_pdf_zebra.py`: nome da fila USB, conversão **legada** e `send_raw` pelo spooler; `send_raw` depende de Windows/pywin32.
- `zebra_ipp_manager.py`: subprocesso da aplicação do servidor, botões de inicializar/interromper/reiniciar, visualização de stdout, filtragem e teste TCP.
- `Verificador/verificador_zebra.py`: verificação independente de TCP, HTTP, resposta IPP, mDNS e, quando disponível, informações do Windows; não imprime.

## Protocolos e formatos

- IPP/2.0 sobre HTTP; operações implementadas no código (não a especificação completa).
- mDNS/DNS-SD `_ipp._tcp.local.` opcional para descoberta.
- Formatos anunciados: `application/pdf`, `image/jpeg`, `image/png`.
- Spooler do Windows: documentos do tipo `RAW`, contendo ZPL.

Não anuncia recursos não implementados, como IPP Everywhere, PWG Raster, PCLm, AirPrint e URF.

## Perfil da etiqueta

O arquivo de configuração utilizado na investigação apontou para `^PW480`, `^LL879`, `^PON`; a cabeça de impressão corresponde ao eixo de aproximadamente 60 mm, e o comprimento de avanço a aproximadamente 110 mm. O modo legado ainda usa um raster intermediário 480 × 832 — **não confundir com o raster final**.

O modo `smart` é o padrão. O Android pode declarar mídia A4, mesmo quando a etiqueta física é 110 × 60 mm: o layout tenta extrair o conteúdo útil, mas o número de páginas deve ser verificado antes da impressão real.

## Tratamento de lotes

Cada página PDF pode corresponder a uma etiqueta. O atributo `copies` repete o conteúdo. Os limites padrão são 500 páginas e 1000 etiquetas por trabalho; a fila suporta vários trabalhos, processados por um worker. O `SpoolBatch` pode juntar múltiplos ZPLs por envio RAW, configurável por número de etiquetas e tamanho em bytes.

A fila mantém estado em memória e documentos temporários; **não possui recuperação garantida após interrupção inesperada**. Envio RAW ao spooler não equivale à confirmação física de impressão.

## Fluxo seguro

Sem `--print`, o servidor não envia ao spooler: gera arquivos de prévia em `previews_ipp/`. Na interface, a opção **Prévia** deve ser usada antes de ativar **Impressão**. `--calibrate` e `--test-file` processam localmente e encerram o programa — não mantêm o servidor de rede ativo.
