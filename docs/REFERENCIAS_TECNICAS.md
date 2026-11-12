# Referências técnicas e bibliotecas

Estas fontes são indicadas para conferência do comportamento dos protocolos e das dependências. As conclusões do histórico do projeto foram derivadas dos arquivos e relatos da implementação, não de ensaios certificados.

1. **RFC 8010** — Internet Printing Protocol/1.1: Encoding and Transport. https://www.rfc-editor.org/rfc/rfc8010
2. **RFC 8011** — Internet Printing Protocol/1.1: Model and Semantics. https://www.rfc-editor.org/rfc/rfc8011
3. **Zebra Technologies** — ZPL II Programming Guide e recursos de suporte de impressoras Zebra. https://www.zebra.com/us/en/support-downloads.html
4. **PyMuPDF** — documentação da renderização de PDF. https://pymupdf.readthedocs.io/
5. **Pillow** — documentação de processamento de imagens. https://pillow.readthedocs.io/
6. **python-zeroconf** — biblioteca de descoberta de serviços por mDNS/DNS-SD. https://python-zeroconf.readthedocs.io/
7. **pywin32** — extensões Windows para Python, incluindo impressão pelo spooler. https://github.com/mhammond/pywin32
8. **PyInstaller** — empacotamento de aplicativos Python. https://pyinstaller.org/en/stable/
9. **GitHub Docs** — organização de repositórios e criação de releases. https://docs.github.com/

**Dependências efetivamente declaradas:** `requirements.txt`. Tkinter pertence à distribuição padrão de Python, quando instalado com suporte a Tcl/Tk. O PyInstaller é uma dependência de build da interface, instalada por `Gerar_EXE.bat`.
