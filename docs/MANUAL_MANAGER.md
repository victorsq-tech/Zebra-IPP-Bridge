# Zebra IPP Manager para Windows 11

Interface para executar o servidor Zebra IPP da sua instalação. O gerenciador usa o Python do projeto e chama `ipp_server.py` na pasta original, onde o servidor carrega o formatador, o motor ZPL e a integração com a Zebra USB. O aplicativo não modifica os módulos, o driver, a fila do Windows ou o firewall.

## Instalação

1. Coloque o projeto em `C:\ZebraIPP` ou selecione a pasta correspondente na interface. Nessa pasta devem estar `ipp_server.py`, `zebra_formatter.py`, `zebra_fast_engine.py` e o seu `print_pdf_zebra.py` original. Mantenha também os demais arquivos e recursos usados pela sua instalação.
2. Use o mesmo Python que já executa o servidor. Se estiver instalando o projeto pela primeira vez e o pacote incluir `requirements.txt`, execute estes comandos na pasta do servidor com a versão de Python exigida pelo projeto.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
   .\.venv\Scripts\python.exe -m pip check
   .\.venv\Scripts\python.exe -u .\ipp_server.py --help
   ```

   `pip check` verifica conflitos entre pacotes instalados. `--help` verifica se o script chega ao analisador de argumentos e lista as opções da sua versão. Se a distribuição incluir `verificar_integracao.py`, consulte o manual original e rode esse teste com o mesmo interpretador. Em caso de `ModuleNotFoundError`, revise os requisitos do seu pacote nesse ambiente Python.
3. Abra `ZebraIPPManager.exe` se já tiver gerado o executável, ou execute o código-fonte conforme abaixo. Na interface, deixe **Python do projeto** vazio para usar `.venv\Scripts\python.exe` da pasta selecionada, ou indique o caminho do `python.exe` que já funciona com o servidor.

## Execução pelo código-fonte

Com Python 3.10 ou superior e Tcl/Tk instalados, abra o PowerShell na pasta deste README e execute:

```powershell
py -m tkinter
py .\zebra_ipp_manager.py
```

O primeiro comando deve abrir a janela de teste do Tk. Feche essa janela antes de seguir.

## Operação

1. Comece em **Prévia**, com IP `127.0.0.1` para um teste no próprio PC. Para testar pelo Android, informe o IPv4 do computador acessível na rede local. Se necessário, use `ipconfig` no Windows para identificar o endereço.
2. Escolha a porta **631** ou **8631**. Se o servidor relatar que a porta está em uso, encerre a instância anterior ou use a outra porta. Use a mesma porta ao testar a conexão.
3. Em **Modo de layout**, o padrão é `smart`. Para margens, escala, rotação ou outros ajustes disponíveis, clique em **Opções do servidor** com ele parado e consulte a saída. Digite cada argumento em uma linha. Uma opção com valor pode ocupar duas linhas, primeiro a opção e depois o valor. Por exemplo, use uma linha com `--debug` se ela constar na ajuda.
4. Clique em **Iniciar**. **Processo ativo** indica que o Python iniciou. Consulte os eventos do servidor e use **Testar TCP** para verificar se a porta aceita conexão a partir do PC. O teste TCP não identifica qual programa respondeu. Use o Android para confirmar a comunicação IPP de ponta a ponta.
5. Depois de validar a prévia, selecione **Impressão** e clique em **Reiniciar**. O gerenciador acrescenta `--print --spool-batch-labels 1`, conforme o comando do projeto anterior. A fila usada é a que seu projeto original configura. Para conferir a fila no Windows, abra **Configurações → Bluetooth e dispositivos → Impressoras e scanners**.

**Interromper** termina o processo Python. **Reiniciar** espera o encerramento e aplica os valores atuais dos campos. Aguarde o fim dos trabalhos antes de interromper, reiniciar ou fechar a janela. Etiquetas já entregues à fila do Windows podem continuar sendo impressas.

## Eventos e exportação

A janela reúne a saída do servidor e do gerenciador. Cada linha recebe a data e a hora locais quando é exibida. Os níveis dos eventos do servidor são estimados a partir do texto original. **Nível** e **Buscar** podem ser combinados. **Exportar visão** grava em UTF-8 as linhas que correspondem aos filtros. Selecione **Todos** e limpe a busca para exportar o histórico disponível, limitado às últimas 5.000 linhas.

## Build com PyInstaller

1. No outro PC com Windows 11, instale o Python 3.10 ou superior com o componente **Tcl/Tk e IDLE**. Para gerar um executável x64, use Python de 64 bits.
2. Extraia todo o ZIP para uma pasta onde você possa gravar arquivos.
3. Dê dois cliques em **Gerar_EXE.bat**. O script cria o ambiente isolado `.build-venv`, verifica o Tcl/Tk, instala o PyInstaller (requer acesso ao índice de pacotes Python) e gera **`dist\ZebraIPPManager.exe`**.

Você pode gerar o executável em um PC sem a Zebra ou a pasta `C:\ZebraIPP`. Depois, copie o executável para o PC que vai operar a impressora e selecione a pasta do projeto e o Python do servidor na interface.

Se preferir executar o build manualmente, abra o PowerShell na pasta extraída:

```powershell
py -m venv .build-venv
$buildPython = ".\.build-venv\Scripts\python.exe"
& $buildPython -m pip install PyInstaller
& $buildPython -m PyInstaller --noconfirm --onefile --windowed --name ZebraIPPManager .\zebra_ipp_manager.py
```

O resultado do build fica em `dist\ZebraIPPManager.exe`. O PyInstaller inclui a interface e seu runtime. Na máquina de destino, o servidor continua precisando do Python do projeto, dos quatro módulos, de suas dependências e da fila Zebra configurada para impressão. [Documentação do PyInstaller](https://pyinstaller.org/en/latest/usage.html)

## Validação na instalação Zebra

Neste ambiente Windows, a interface foi testada com um servidor simulado. O teste cobriu a montagem dos comandos, a consulta de opções, o início, a interrupção, o reinício com novas configurações, a captura de falhas, os filtros, a exportação e o diagnóstico TCP. O arquivo ZIP enviado pelo usuário continha uma compilação existente em `dist/ZebraIPPManager.exe`, que não foi executada no ambiente de organização do repositório. Para distribuir versões futuras, gere e teste novamente o executável no Windows.

Os módulos e o arquivo de requisitos estão incluídos nesta edição do repositório; a disponibilidade de dependências no Windows e a compatibilidade com os periféricos ainda precisam de conferência local. Para validar na instalação final, abra primeiro **Opções do servidor**, inicie em **Prévia**, teste TCP, envie um documento pelo Android e verifique os eventos e a prévia gerada. Reinicie em **Impressão** e envie uma etiqueta de teste para confirmar fila USB, tamanho, posição e orientação.
