# Verificador Zebra IPP — conexão, portas e serviços

Programa independente e **somente de diagnóstico** do projeto Zebra ZD220 USB ↔ Windows 11 ↔ IPP ↔ tablet Android. Não transmite etiquetas, não executa `Print-Job`, não modifica firewall nem inicia o servidor de impressão.

## Arquivos

- `verificador_zebra.py`: diagnóstico com interface gráfica e linha de comando (Python 3.10+).
- `Abrir_Verificador.bat`: duplo clique para abrir a interface gráfica no Windows.
- `Verificar_no_PowerShell.bat`: diagnóstico de console e relatório salvo na pasta `relatorios`.
- `test_verificador.py`: testes locais com servidor IPP simulado, sem impressora.

## Instalação e uso

1. Extraia o ZIP, por exemplo em `C:\ZebraIPP\Verificador`.
2. **Inicie o servidor IPP** na janela de PowerShell habitual, por exemplo:

   ```powershell
   cd C:\ZebraIPP
   py .\ipp_server.py --ip 192.168.10.76 --port 631
   ```

   **Não use `--print` para executar o diagnóstico.**
3. Abra `Abrir_Verificador.bat` e clique em **Verificar conexão e portas**.
4. Confira o resultado. Clique em **Salvar relatório** para gerar arquivos TXT e JSON, úteis para investigação de erros.

Alternativamente, no PowerShell:

```powershell
cd C:\ZebraIPP\Verificador
py .\verificador_zebra.py --ip 192.168.10.76 --port 631 --output .\relatorios
```

Se o servidor estiver em 8631, troque para `--port 8631`. Para gerar JSON no console, inclua `--json`.

## O que é verificado

| Verificação | Interpretação |
|---|---|
| TCP 631 ou 8631 (conforme escolha) | Servidor aceita conexões na porta IPP |
| TCP 631 e 8631 alternativos | Informativo: podem estar fechados |
| TCP 9100 | Informativo: porta RAW não é necessária para esta ponte |
| HTTP GET `/` | Servidor responde no IP indicado |
| IPP `Get-Printer-Attributes` | Servidor responde protocolo IPP válido com nome e formatos |
| DNS-SD `_ipp._tcp.local.` | O computador descobre anúncio mDNS na rede (precisa `zeroconf`) |
| Perfil de rede Windows | Perfil Público/Privado, leitura via PowerShell |
| Processo TCP | Mostra PID da porta configurada, se disponível |
| Fila USB Zebra | Presença/nome/driver/porta da fila Windows |
| Regras de firewall | Lista regras ativadas com Zebra ou mDNS no nome; não altera regras |
| Dependências | Identifica `zeroconf`, `Pillow`, `PyMuPDF`, `pywin32` |

### Importante: diagnóstico não alcança automaticamente o Android

- Acesso HTTP do tablet e mDNS no próprio tablet precisam ser testados **no tablet**.
- No navegador do tablet, abra `http://192.168.10.76:631/` (ou porta usada pelo servidor).
- No navegador de mDNS do tablet, procure `_ipp._tcp.local.` com `rp=ipp/print` e porta esperada.
- Se o tablet encontrar o anúncio, mas a impressora não aparecer no serviço de impressão, isso **não é necessariamente um bloqueio de firewall**; o serviço Android pode rejeitar capacidades ou possuir uma configuração antiga.
- **UDP 5353 não é uma porta TCP**: não se testa sua descoberta abrindo conexão TCP para 5353. O aplicativo verifica a descoberta funcional DNS-SD local.
- Uma regra de firewall 'Allow' não prova por si só que os datagramas mDNS chegam ao tablet.

## Segurança

- Não solicita privilégios de administrador.
- Não abre portas próprias de servidor nem imprime etiquetas.
- Não realiza varredura ampla da rede: verifica apenas o IP informado e portas específicas.
- Os relatórios contêm IP local, nome de impressora e detalhes do sistema. Compartilhe apenas quando necessário.

## Teste de funcionamento do verificador

```powershell
py .\test_verificador.py
```

Esses testes iniciam uma **simulação local** do endpoint IPP para validar as consultas, e não dependem do hardware Zebra.
