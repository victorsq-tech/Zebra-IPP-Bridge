# Preparar e publicar o Zebra IPP Bridge no GitHub

## Antes de publicar

O projeto recebido tinha ambiente virtual Windows, `build/`, `dist/`, cópias antigas e `previews_ipp/` de testes operacionais. **Esses itens não foram incluídos no ZIP do repositório**; o `.gitignore` também os bloqueia em commits futuros.

Revise especialmente: logs, PDFs recebidos do Android, arquivos `.zpl` gerados de pedidos reais, etiquetas com dados de clientes, endereços IP ou nomes de usuário específicos, credenciais e arquivos de configuração privada. O endereço 192.168.10.76 aparece apenas como **exemplo**, e deve ser substituído por cada instalador.

### Licenciamento

Não escolhemos uma licença sem a autorização do responsável. Um repositório público **sem arquivo `LICENSE`** permite visualizar o código, mas **não autoriza automaticamente redistribuição ou reutilização**. Se desejar código aberto, escolha e inclua uma licença adequada (ex.: MIT, Apache-2.0 ou GPL) considerando seus objetivos e atribuições de terceiros.

### Publicar o código-fonte

1. Extraia `ZebraIPP_GitHub_Repositorio.zip` em uma pasta vazia (ex.: `ZebraIPP-GitHub`).
2. Abra o terminal dentro da pasta que contém `README.md` e `ipp_server.py`.
3. Confira o que será adicionado: `git status` e `git add --dry-run .`.
4. Inicialize e prepare o primeiro commit:

```powershell
git init -b main
git add .
git status
git commit -m "docs: estrutura inicial e documentacao do uso de IA"
```

5. No site do GitHub, crie um repositório novo, de preferência **privado** inicialmente, sem adicionar README ou licença automaticamente (pois este pacote já os prepara).
6. No terminal, associe o repositório (substitua o nome e a URL pelos seus):

```powershell
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Caso não tenha configurado nome/email do Git, configure sua identidade no ambiente antes do commit. **Não inclua tokens ou senhas na linha de comando nem em arquivos versionados.**

### Distribuição da GUI `.exe`

A pasta `dist/` do ZIP original continha um `ZebraIPPManager.exe`, **não incluído no ZIP do repositório-fonte**. Para disponibilizar binários, reconstrua a interface em Windows com `Gerar_EXE.bat`, teste o arquivo resultante, verifique o antivírus e anexe o EXE ou um pacote ZIP ao recurso *Releases* do GitHub. Informe claramente que o EXE é **somente o gerenciador**, e exige Python, módulos do servidor, dependências e a fila Zebra já instalada.

### Sugestão de descrição do repositório

> Ponte IPP experimental em Python para imprimir etiquetas na Zebra ZD220 USB a partir do Android, com GUI Windows, conversão PDF/JPEG/PNG → ZPL, diagnóstico de rede e documentação do uso de IA.

### Sugestão de tópicos

`python`, `ipp`, `zpl`, `zebra-printer`, `windows`, `android`, `printing`, `tkinter`, `generative-ai`

## Checklist de revisão humana

- [ ] Executar `verificar_integracao.py` no Windows com a `.venv` limpa.
- [ ] Conferir impressão em prévia antes de usar `--print`.
- [ ] Conferir a fila USB e fazer testes repetidos após a correção dos estados IPP.
- [ ] Inspecionar `git diff --cached` para remover dados de clientes e segredos.
- [ ] Escolher a licença, se desejar permitir reutilização.
- [ ] Publicar primeiro como privado, revisar e então decidir se o projeto será público.
- [ ] Atualizar o documento `USO_DE_IA_NO_PROJETO.md` conforme novos resultados.
