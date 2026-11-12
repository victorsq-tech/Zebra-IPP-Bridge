# Plano de validação, evidências e limitações

## Evidências que acompanham o projeto

| Verificação | Onde observar | O que ela prova | O que não prova |
|---|---|---|---|
| Imports e conversão em 480×879 | `verificar_integracao.py` | Módulos conectados em teste local | Impressão física |
| Formatação | `tests/test_formatting.py` | Raster e prévia para PDF A4 e imagens | Precisão da mídia real |
| Codificador e fila | `tests/test_optimized.py` | Bytes ZPL e enfileiramento em spooler simulado | Desempenho real da Zebra |
| IPP PDF/JPEG/PNG | `tests/test_http_extended.py` | HTTP local, chunked e recebimento no servidor | Interoperabilidade universal Android |
| Diagnóstico | `Verificador/test_verificador.py` | Consultas HTTP/IPP em servidor falso | Descoberta real por multicast |
| Impressão com equipamento | Teste manual, não incluído no ZIP | Saída física e avanço correto | Estabilidade além do período observado |

## Rodar testes sem imprimir

No Windows com `.venv` e dependências instaladas:

```powershell
.\.venv\Scripts\python.exe .\verificar_integracao.py
.\.venv\Scripts\python.exe .\tests\test_formatting.py
.\.venv\Scripts\python.exe .\tests\test_optimized.py
.\.venv\Scripts\python.exe .\tests\test_http_extended.py
.\.venv\Scripts\python.exe .\Verificador\test_verificador.py
```

Os testes usam simulações para `send_raw`, não enviam comandos USB reais. Use uma impressora de teste em local seguro e **não use** `--print` durante a validação automática.

## Plano manual de aceitação (Windows/Android/Zebra)

1. Confirme `ipconfig`, nome da fila USB, papel 110 × 60 mm e ausência de documentos pendentes antigos.
2. Inicie o servidor em `smart`/prévia, porta 631, com o IPv4 LAN correto.
3. Execute o verificador de conexão: TCP, HTTP, IPP e anúncio mDNS.
4. Envie uma única etiqueta do Android; confira o `Print-Job` e a quantidade de páginas do PDF, especialmente quando mídia A4 for solicitada.
5. Compare PNG e ZPL gerados, orientação, margens e códigos de barras.
6. Habilite `--print --spool-batch-labels 1` e faça uma impressão física isolada.
7. Envie **ao menos dez trabalhos em sequência**, acompanhando números de trabalho, estados IPP, fila do Windows e saída física.
8. Teste um lote pequeno com cópias; depois aumente gradualmente.
9. Registre fabricante/firmware do Android, versão do serviço de impressão, driver e versão do Windows.
10. Se houver travamento, salve logs e informações da fila antes de reiniciar, removendo dados pessoais.

## Falhas e pontos abertos

- Há relato real de **travamento percebido no terceiro envio** após duas impressões bem-sucedidas, com consultas de status IPP repetitivas. O sistema ainda requer validação após as correções de `Get-Jobs` e estado dos trabalhos.
- O Android em certos testes solicitou A4 enquanto a impressora usa etiquetas 110 × 60 mm; isso pode introduzir páginas adicionais ou exigir enquadramento especial.
- O spooler aceita dados RAW, mas o servidor não mede nem confirma fisicamente a conclusão de cada etiqueta.
- A fila não é durável em casos de falta de energia ou encerramento inesperado.
- IPP sem TLS/autenticação não deve ficar disponível fora da rede local confiável.
- A GUI não instala automaticamente a Zebra ou as dependências do servidor; requer Python e ambiente corretamente configurados.
- Arquivos ZPL, prévias e relatórios devem ser excluídos do repositório público se contiverem dados de clientes.

## Modelo de registro de teste

| Campo | Preencher após execução |
|---|---|
| Data e responsável | — |
| Windows e nome exato da fila | — |
| Tablet, versão Android e serviço de impressão | — |
| IP/porta e arquivo enviado | — |
| Páginas/cópias esperadas e produzidas | — |
| Status IPP e IDs de trabalho | — |
| Resultado físico (quantidade, corte, legibilidade) | — |
| Logs anonimizados e evidências | — |
| Resultado / próxima ação | — |
