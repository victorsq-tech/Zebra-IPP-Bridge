# Histórico técnico e decisões de projeto

> Registro reconstruído do código atual e das conversas disponíveis. Não equivale a um changelog de commits anterior.

## Iterações identificadas

**1. Ponte Windows USB -> Android.** A simples exposição da porta RAW 9100 no computador não era reconhecida automaticamente pelo sistema Android. Foi adotada uma ponte de aplicação que recebe IPP em HTTP e envia ZPL RAW à fila USB Windows.

**2. IPP e descoberta local.** Foram implementadas operações de impressora/trabalho, respostas em formato IPP e anúncio mDNS `_ipp._tcp`. Endereço de teste registrado: 192.168.10.76:631; o valor é específico da rede de desenvolvimento.

**3. Conversão e prévias.** PDFs recebidos do Android foram renderizados por PyMuPDF. Foram corrigidos erros de modo RGB e discutidas margens, enquadramento, orientação e diferenças entre prévia e impressão física.

**4. Perfil ZPL.** O arquivo de configuração gerado pelo utilitário Zebra indicou `^PW480` e `^LL879`, adotados para o bitmap final. Não usar `^JUS` nos trabalhos regulares.

**5. Lotes e otimização.** Uma página do PDF representa uma etiqueta; foram adicionados limite de páginas/cópias, codificador ZPL de bits via Pillow, prévias opcionais e agrupamento `SpoolBatch`. Foi introduzida fila com trabalhador único para responder rapidamente ao cliente IPP.

**6. Formatação inteligente.** Foi criado `zebra_formatter.py` para recortar conteúdo útil de PDFs A4, renderizar a região em resolução apropriada e permitir alinhamentos e deslocamentos. `legacy` ficou disponível para comparação.

**7. Observabilidade.** Foram adicionados um verificador de conexões e uma GUI Tkinter `ZebraIPPManager`, com controle de processo, logs, filtros e exportação.

**8. Diagnóstico em 11/11/2026.** Um `ModuleNotFoundError: pymupdf` indicou ambiente Python incorreto (`.build-venv` em lugar do ambiente de execução). Em testes reais houve dois envios bem-sucedidos, depois uma falha percebida; logs mostraram consultas frequentes de status. O servidor passou por ajustes de `Get-Jobs` e estados IPP, ainda pendentes de revalidação física prolongada.

**9. Preparação de publicação.** O material recebido continha cerca de 10 mil entradas, principalmente `.build-venv`, arquivos de compilação e produtos de execução. O repositório público foi separado do ambiente instalado, sem incluir prévias reais, executáveis ou versões antigas no controle de fonte.

## Decisões que não devem ser confundidas com funcionalidades concluídas

- O sistema **não** é um driver genérico certificado nem implementa IPP Everywhere/AirPrint.
- `ZebraIPPManager.exe` contém somente a GUI; o servidor continua executando Python separadamente.
- O `print_pdf_zebra.py` presente no arquivo do usuário é a ponte Windows real; não substituí-lo por stubs de testes.
- A opção de compressão Z64 e repetição `^PQ` são experimentais; o padrão conservador é `hex` e `repeat`.
- Não há serviço Windows instalado automaticamente, nem persistência transacional de fila.
