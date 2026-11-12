# Documentação metodológica: uso de Inteligência Artificial no Zebra IPP Bridge

**Tipo de projeto:** desenvolvimento de software aplicado à comunicação de dispositivos e automação de impressão.

**Objeto:** ponte entre a impressora Zebra ZD220 conectada por USB em Windows 11 e clientes Android que enviam documentos pelo protocolo IPP.

**Ferramenta de apoio:** ChatGPT, da OpenAI (assistente generativo utilizado em conversas iterativas). As versões/modelos exatos empregados em cada etapa não foram registrados de maneira verificável no arquivo analisado; portanto, não são atribuídos a uma versão específica.

**Fonte desta documentação:** histórico de desenvolvimento relatado pelo usuário na conversa e arquivos do `ZebraIPP.zip` disponibilizado para preparação do repositório em **11 de novembro de 2026**. Este documento descreve o processo conforme essas evidências, sem alegar histórico Git, testes físicos ou autoria individual de linhas que não possam ser comprovados.

## 1. Objetivo do uso da IA

Empregar IA generativa como **assistente de engenharia** para apoiar a investigação de uma necessidade prática: permitir que um tablet Android se comunique com uma Zebra ZD220 instalada via USB em um computador Windows 11, usando a rede local. A IA ajudou a propor alternativas de arquitetura, produzir e revisar trechos de código Python, interpretar logs, estruturar testes e redigir documentação.

A IA **não substituiu** a configuração da rede, os testes de comunicação com o tablet, o ajuste da mídia física, nem a decisão de habilitar a impressão real. Essas atividades exigiram execução e observação no ambiente do usuário.

## 2. Problema inicial e requisitos informados

- Equipamento: **Zebra ZD220-203dpi ZPL** conectada por USB no Windows 11.
- Cliente: dispositivo **Android**, pretendendo utilizar o sistema de impressão por rede.
- Comunicação: IPP sobre HTTP, com tentativa de descoberta mDNS/DNS-SD (`_ipp._tcp.local.`).
- Formatos: PDF e, após iterações, JPEG/PNG.
- Papel: etiqueta 110 × 60 mm; perfil de impressão observado `^PW480` / `^LL879`.
- Necessidade operacional: várias etiquetas por lote, prévia, formatação e monitoramento de conexão em interface gráfica.

Os endereços IPv4 específicos, nome da fila e caminhos apresentados no código são **valores de referência do ambiente original**, não configurações universais.

## 3. Método de trabalho com IA

O desenvolvimento ocorreu em **ciclos de especificação → proposta/implementação → execução → observação → correção**:

1. **Descrição do problema pelo operador:** equipamentos, portas, sintomas e resultado esperado.
2. **Análise e hipótese com apoio da IA:** levantamento de causas possíveis, requisitos de IPP/mDNS e transformações de raster/ZPL.
3. **Geração/refatoração assistida:** construção de scripts, módulos, parâmetros de execução e testes simulados.
4. **Execução pelo responsável:** configuração de Windows/USB/tablet, instalação de dependências e tentativa de impressão.
5. **Retorno de evidências:** logs de PowerShell/Manager, exceções Python, tamanhos de PDFs, contagem de páginas e comportamento observado.
6. **Revisão e documentação:** ajustes no código, testes automatizados e instruções operacionais.

**Importante:** sugestões da IA são hipóteses até que testes reproduzíveis as confirmem. Uma resposta IPP com status `0x0000` ou o envio de bytes ao spooler não prova que a etiqueta foi impressa fisicamente.

## 4. Evolução do projeto e contribuições da IA

| Etapa | Solicitação/evidência | Apoio da IA | Evidência técnica nos arquivos |
|---|---|---|---|
| Compartilhamento inicial | Zebra USB não era diretamente acessível no Android via IP/porta 9100 | Proposição de ponte de impressão por Python, HTTP e IPP | `ipp_server.py`, `print_pdf_zebra.py` |
| Descoberta e compatibilidade | Tablet não reconhecia o endereço como impressora; respostas IPP precisavam ser revistas | Implementação/revisão de atributos IPP e anúncio `_ipp._tcp` | `printer_attrs`, `Handler`, blocos mDNS em `ipp_server.py` |
| Conversão de documentos | Problemas com RGB, orientação e margens; PDF recebido do Android podia usar A4 | Geração de fluxo PDF/PNG/JPEG → raster → ZPL e modo seguro de prévia | `zebra_formatter.py`, `zebra_fast_engine.py` |
| Perfil físico | Necessidade de respeitar medidas da Zebra | Ajuste do perfil para 480 × 879 pontos, separando a mídia do raster | `ZebraProfile`, constantes ZPL |
| Otimização | Lotes com muitas páginas/cópias e desempenho do codificador | Encapsulamento de `^GFA`, fila com trabalhador, leitura em blocos e `SpoolBatch` | `zebra_fast_engine.py`, fila do `ipp_server.py` |
| Diagnóstico | Necessidade de verificar portas e eventos | Verificador TCP/HTTP/IPP/mDNS e interface de logs | `Verificador/verificador_zebra.py`, `zebra_ipp_manager.py` |
| Depuração real | `ModuleNotFoundError: pymupdf`; consultas IPP repetitivas e falha após envios sucessivos | Interpretação de logs, recomendações de ambiente e ajustes de estado IPP | `requirements.txt`, `Instalar.bat`, implementação de `Get-Jobs` |
| Preparação da publicação | Diretório local com ambientes Python, executável e prévias | Separação do repositório-fonte e documentação do processo | `.gitignore`, `README.md`, `docs/` |

A tabela apresenta **o papel observado da IA nas iterações**, e não uma garantia de que todo trecho de código foi produzido exclusivamente por ela.

## 5. Exemplo documentado de depuração assistida

### Dependência instalada no ambiente errado

Em **11/11/2026**, o Manager registrou `ModuleNotFoundError: No module named 'pymupdf'` ao iniciar `ipp_server.py` com `C:\ZebraIPP\.build-venv\Scripts\python.exe`. A análise distinguiu o ambiente usado para **construir a interface executável** do ambiente Python necessário para **executar o servidor**. A orientação resultante foi criar/usar `.venv`, instalar `requirements.txt` no interpretador selecionado e conferir `import pymupdf, PIL, zeroconf, win32print`.

### Lotes e comportamento do Android

Em testes relatados em **11/11/2026**, dois envios foram bem-sucedidos antes de um travamento percebido. Logs mostraram recebimento de PDF, respostas IPP, 3 páginas por trabalho e conclusão do trabalhador de impressão; também exibiram sucessivas consultas `Get-Printer-Attributes` e `Get-Job-Attributes` pelo Android. A investigação levou à revisão do comportamento de `Get-Jobs` e do estado final de trabalhos. **A causa raiz do travamento não foi provada**, e a reprodução física contínua ainda permanece necessária.

## 6. Separação de responsabilidades

**Responsável/usuário do projeto:** definiu o caso de uso, o equipamento e restrições, disponibilizou o código e os logs, executou testes no Windows/Android/Zebra, conferiu resultados e decidiu prioridades e mudanças a aplicar.

**Assistente de IA:** propôs hipóteses, explicou protocolos, elaborou scripts e refatorações, criou verificadores/testes simulados, examinou evidências compartilhadas e apoiou a redação técnica.

**Bibliotecas e plataformas terceirizadas:** Python, PyMuPDF, Pillow, zeroconf, pywin32, Tkinter e PyInstaller fornecem as funcionalidades de execução, conversão, rede, interface e build. O código gerado com IA também está sujeito às licenças dessas ferramentas.

## 7. Verificação da qualidade

### Validado nos testes automatizados descritos no projeto

- Compilação/imports e geração de raster/arquivo ZPL em cenário local.
- Bitmaps `^GFA` comparados com uma implementação de referência por pixel.
- PDF multipágina, JPEG/PNG, transparência e upload HTTP `chunked` nos testes simulados.
- Fila/agrupamento RAW simulados e consultas IPP em servidor local.

### Observado pelo usuário em equipamento real

- Descoberta/conexão do tablet Android com a ponte IPP em parte dos testes.
- Impressões reais relatadas como bem-sucedidas, seguidas de comportamento intermitente após envios repetidos.

### Não comprovado

- Compatibilidade com todas as versões do serviço de impressão Android.
- Impressão de milhares de etiquetas sem falhas, medição de velocidade física ou operação ininterrupta.
- Correspondência de todos os estados IPP ao estado físico da impressora.
- Segurança para exposição do serviço na internet ou certificação de impressão.

## 8. Limitações e riscos de usar IA no desenvolvimento

- A IA pode sugerir parâmetros incompatíveis com a impressora, protocolos incompletos ou dependências ausentes.
- Testes simulados dão confiança sobre **código e protocolo**, não sobre avanço do papel, USB, driver ou firmware.
- Logs enviados à IA devem ser revisados: caminhos, IPs, etiquetas e informações de clientes podem ser sensíveis.
- Mudanças devem ser versionadas para possibilitar comparação, rollback e revisão humana.
- Todo código produzido ou adaptado com IA precisa de revisão funcional, de segurança e de licenças antes da distribuição.

## 9. Reprodutibilidade e transparência

Os scripts `verificar_integracao.py`, `tests/` e `Verificador/test_verificador.py` permitem reproduzir parte dos testes **sem impressora física**. `requirements.txt` define as dependências. Para reproduzir a validação operacional, é necessário um computador Windows com spooler, uma Zebra ZD220 USB, etiquetas 110 × 60 mm e cliente Android, conforme procedimentos em `docs/TESTES_E_LIMITACOES.md`.

O histórico de alterações foi reconstruído das versões e logs disponíveis; **não foi recuperado um histórico de commits Git anterior**. O documento deve ser atualizado quando houver novos testes físicos ou mudanças arquiteturais.

## 10. Declaração resumida de uso de IA (para trabalho acadêmico)

> Este projeto utilizou Inteligência Artificial generativa, por meio do ChatGPT (OpenAI), como ferramenta de apoio ao desenvolvimento de software. A IA contribuiu na análise do protocolo IPP, geração e refatoração de scripts Python, implementação de rotinas de conversão de documentos em ZPL, criação de testes simulados, interpretação de logs e organização da documentação. As necessidades, restrições, configuração do ambiente e testes com os dispositivos foram definidos e conduzidos pelo responsável pelo projeto. As respostas e o código sugeridos pela IA foram tratados como hipóteses técnicas e submetidos a verificações, mantendo-se registradas as limitações dos testes sem hardware e as falhas ainda não solucionadas.

Este texto documenta o **uso da ferramenta**, sem atribuir à IA autoria acadêmica independente ou substituir a responsabilidade técnica de quem publica o projeto.
