# Vision 02 Studio — Galeria vertical ampliada (v14.2)

A grade física 5 × 3 introduzida na v14.1 permanece com **dimensões
fixas**, centralizada na área esquerda. A v14.2 ajusta o **painel direito**,
que antes comprimía as 90 miniaturas na aba **Imagem**.

- Galeria interna com área solicitada de 300 px e rolagem vertical própria.
- Rodapé com os cinco botões de trabalho organizados em **duas colunas**;
  os comandos de prévia, salvamento, aplicação IPC, descarte e edição avançada
  continuam sempre visíveis.
- Novo botão **Abrir galeria ampliada (90 miniaturas)…**, que abre janela
  independente de 820 × 680 px, redimensionável, com pesquisa, rolagem e
  miniaturas de 90 × 90 px.
- Clicar em uma miniatura na janela ampliada usa a mesma seleção local da
  galeria original: atualiza o campo Imagem e solicita prévia, **sem salvar
  YAML ou aplicar IPC**. Fechar a janela descarta apenas a janela, não o
  formulário de propriedades do Studio.
- Em monitores menores, as páginas de propriedades continuam roláveis.

## Instalação pelo Ubuntu

1. Feche o Studio.
2. Em **Vision 02 — Atualizações**, escolha o ZIP `vision02-galeria-vertical-v14-2-update.zip`.
3. **Inspecionar atualização** e **Aplicar e testar**. O gerenciador exige o
   hash exato de `apps/vision02_studio.py` da v14.1 e restaura backup se os
   testes falharem.
4. Reabra o Studio, vá a **Teclas → Imagem**, verifique que há mais linhas
   de ícones visíveis, role dentro da galeria e experimente a janela ampliada.
5. Confira que o painel de ações continua acessível e que a grade 5 × 3
   mantém suas dimensões mesmo com a janela maximizada.

## Preservação

Não modifica serviço, HID, hardware, perfil YAML, biblioteca de ícones,
credenciais OBS ou Git. Os novos controles operam apenas na interface GTK.
