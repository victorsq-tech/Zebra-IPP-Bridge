# Zebra IPP Bridge

**Ponte de impressão IPP para Zebra ZD220 USB no Windows 11, com cliente Android.**

Projeto experimental desenvolvido para disponibilizar uma impressora térmica Zebra, conectada por USB a um computador, como impressora acessível na rede local. Inclui interface gráfica de operação, diagnóstico de portas, conversão de PDF/imagem para ZPL e geração de prévias.

> **Estado atual:** protótipo funcional em testes. Houve impressões reais bem-sucedidas relatadas durante o desenvolvimento, mas também um caso de falha após envios consecutivos. Não há garantia de operação 24/7 nem certificação IPP Everywhere/Mopria. **Use primeiro o modo prévia** e mantenha supervisão durante os testes físicos.

## Arquitetura

```text
Tablet Android (IPP/HTTP; descoberta mDNS)
               |
               v
    ipp_server.py (fila de trabalhos)
               |
        zebra_formatter.py     PDF/JPEG/PNG -> raster 480 x 879
               |
       zebra_fast_engine.py    raster -> ZPL ^GFA
               |
       print_pdf_zebra.py      envio RAW -> spooler Windows -> Zebra USB

zebra_ipp_manager.py           interface gráfica; iniciar/parar, logs e teste TCP
Verificador/verificador_zebra.py   diagnóstico TCP/HTTP/IPP/mDNS/Windows
verificar_integracao.py       validação local sem imprimir
```

## Requisitos

- Windows 11; Zebra ZD220-203dpi ZPL instalada via USB com fila no Windows.
- Python **3.10+** com Tcl/Tk (para executar a interface a partir do código).
- Tablet Android e computador com comunicação na mesma rede local.
- Dependências declaradas em [`requirements.txt`](requirements.txt).

O perfil utilizado nos testes é **`^PW480`, `^LL879`** (raster final 480 × 879 pontos). O módulo legado `print_pdf_zebra.py` ainda usa 480 × 832 na renderização anterior; prefira o layout `smart` e valide a calibração. O nome padrão da fila é `ZDesigner ZD220-203dpi ZPL`; confira o nome real no seu Windows.

## Instalação (Windows 11)

Extraia ou clone o projeto e abra o PowerShell na pasta. Se preferir, execute `Instalar.bat`, que cria `.venv` e instala os requisitos.

```powershell
cd C:\ZebraIPP
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\verificar_integracao.py
```

**Atenção ao Python selecionado:** o `ZebraIPPManager.exe` é uma interface de controle; o servidor roda com o Python indicado nela. No campo **Python do projeto**, deixe vazio para usar `.venv\Scripts\python.exe`, ou selecione um interpretador com PyMuPDF, Pillow, zeroconf e pywin32 instalados. Evite usar `.build-venv` do PyInstaller para executar o servidor: ele pode não conter essas bibliotecas.

## Uso rápido

1. Confira o IPv4 do PC com `ipconfig`. Não use `127.x.x.x` para acesso por outro dispositivo.
2. Execute `Iniciar_Manager.bat` ou `py zebra_ipp_manager.py` (com as dependências da interface disponíveis).
3. Na interface, selecione a pasta do projeto e o Python da `.venv`, informe o **IPv4 LAN real**, porta **631** e layout **smart**.
4. Use **Prévia** primeiro. Clique em **Iniciar**, envie uma etiqueta no Android e confira os arquivos em `previews_ipp/`.
5. Só depois de validar orientação, contagem e dimensões, reinicie em **Impressão**. A interface usa `--print --spool-batch-labels 1`.
6. Para diagnóstico, execute `Verificador/Abrir_Verificador.bat` ou o comando indicado abaixo.

Sem interface, o servidor pode ser iniciado manualmente (substitua o IP pelo IPv4 do seu PC):

```powershell
.\.venv\Scripts\python.exe .\ipp_server.py --ip 192.168.10.76 --port 631 --layout-mode smart --debug
```

**Impressão real — somente depois de validar:**

```powershell
.\.venv\Scripts\python.exe .\ipp_server.py --ip 192.168.10.76 --port 631 --layout-mode smart --print --spool-batch-labels 1
```

Verificação de rede (não imprime):

```powershell
.\.venv\Scripts\python.exe .\Verificador\verificador_zebra.py --ip 192.168.10.76 --port 631
```

Testar apenas o fluxo PDF -> prévia, sem rede ou impressão:

```powershell
.\.venv\Scripts\python.exe .\ipp_server.py --ip 127.0.0.1 --test-file .\examples\exemplo_a4_com_etiqueta.pdf --layout-mode smart
```

> O servidor usa **8631 como porta padrão interna** quando `--port` não é informado; para o projeto e o Manager, recomendamos **especificar sempre `--port 631`** (ou outra porta consistente com o cliente Android).

## Componentes

| Arquivo/pasta | Responsabilidade |
|---|---|
| `ipp_server.py` | IPP/HTTP, filas, trabalhos, conversão, anúncios mDNS |
| `zebra_formatter.py` | Recorte do conteúdo, orientação, margens e raster |
| `zebra_fast_engine.py` | Codificação ZPL `^GFA` e agrupamento RAW |
| `print_pdf_zebra.py` | Comunicação RAW com o spooler USB via pywin32; suporte legado |
| `zebra_ipp_manager.py` | GUI Tkinter com logs e comandos do servidor |
| `Verificador/` | Diagnóstico de conexões, portas, IPP e mDNS |
| `verificar_integracao.py` | Teste do encadeamento dos motores sem impressão física |
| `tests/` | Testes locais com simulação de impressora |
| `examples/` | Amostras sintéticas de PDF e prévia |
| `Instalar.bat` / `Iniciar_Manager.bat` | Preparação e início da interface no Windows |
| `Gerar_EXE.bat` | Gera o executável da **interface**, não do servidor inteiro |

## Testes

```powershell
.\.venv\Scripts\python.exe .\verificar_integracao.py
.\.venv\Scripts\python.exe .\tests\test_formatting.py
.\.venv\Scripts\python.exe .\tests\test_optimized.py
.\.venv\Scripts\python.exe .\tests\test_http_extended.py
.\.venv\Scripts\python.exe .\Verificador\test_verificador.py
```

Os testes automatizados não comprovam impressão USB real. Há falhas de estabilidade reportadas após envios repetidos; veja [limitações e próximos passos](docs/TESTES_E_LIMITACOES.md).

## Executável Windows

A partir do código-fonte, execute `Gerar_EXE.bat` no **Windows**. O resultado será `dist\ZebraIPPManager.exe`. Ele somente controla o processo do servidor e exibe seus logs; não empacota a dependência do driver e os motores no mesmo executável. O executável preexistente da pasta `dist/` do arquivo de origem **não foi incluído neste repositório**; publique binários verificados separadamente em *GitHub Releases*, se desejar.

## Documentação

- [Como a IA foi utilizada no desenvolvimento](docs/USO_DE_IA_NO_PROJETO.md)
- [Arquitetura e fluxo de dados](docs/ARQUITETURA.md)
- [Testes, limitações e validação](docs/TESTES_E_LIMITACOES.md)
- [Publicação responsável no GitHub](docs/GUIA_PUBLICACAO_GITHUB.md)
- [Histórico técnico de decisões](docs/HISTORICO_E_DECISOES.md)
- [Referências técnicas](docs/REFERENCIAS_TECNICAS.md)
- [Manual do Zebra IPP Manager](docs/MANUAL_MANAGER.md)

## Segurança, privacidade e escopo

O IPP experimental não implementa autenticação, criptografia TLS ou uma autorização de clientes. Execute apenas em rede local confiável; **não exponha a porta diretamente à internet**. Prévias, ZPL, PDFs e relatórios podem conter dados operacionais e pessoais; por isso as pastas de execução e os logs estão excluídos por `.gitignore`. Revise alterações e o conteúdo de qualquer commit antes de publicar.

**Licença:** ainda não definida pelo responsável pelo projeto. Consulte [`docs/GUIA_PUBLICACAO_GITHUB.md`](docs/GUIA_PUBLICACAO_GITHUB.md) antes de escolher uma licença de código aberto.
