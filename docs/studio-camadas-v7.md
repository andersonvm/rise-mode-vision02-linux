# Vision 02 Studio — v7: prévia com camadas RGBA e visibilidade real

A v7 permite **ocultar os pixels de Imagem e/ou Texto apenas na prévia da aba
Composição**. Os controles são locais à sessão: não marcam o formulário como
alterado, não salvam YAML e não aplicam nada ao dispositivo. O bloqueio de
camadas e as molduras da v6 continuam independentes da visibilidade de pixels.

## Pipeline

O renderizador do LCD (`vision02.rendering.render_appearance`, `render_key` e
`render_profile`) **não foi modificado**. O backend do Studio continua
fornecendo `image`, que é a mesma prévia RGB do equipamento, e agora acrescenta:

- `layers`: caminhos para quatro PNGs locais com os modos `both`, `image`,
  `text` e `none`; as variantes são renderizadas separadamente pelo pipeline
  original, para preservar os pixels e o antialiasing do renderizador existente.
- `components`: três PNGs **RGBA** (fundo opaco, imagem transparente e texto
  transparente) destinados a edições futuras por canal de transparência.

As variantes são geradas **somente para a tecla selecionada**, quando ela possui
`appearance` personalizado. Os outros 15 previews tradicionais continuam
inalterados. A imagem na aba Imagem (`quick_picture`) permanece completa;
apenas o `composition_picture` é atualizado ao alternar visibilidade.

A escolha das variantes obedece à tabela:

| Mostrar Imagem | Mostrar Texto | Modo |
|:--:|:--:|---|
| sim | sim | `both` (igual ao LCD) |
| sim | não | `image` |
| não | sim | `text` |
| não | não | `none` (fundo) |

O cache é gerado sob `$XDG_CACHE_HOME/vision02/editor` (ou `~/.cache/vision02/editor`).
A geração usa o backend Python do `.venv`; a interface GTK4 usa o Python do
sistema. Nenhum novo componente é exigido pelo serviço HID.

## Limitações deliberadas

- A v7 **não** permite esconder camadas no LCD: o ajuste não é salvo.
- Sem aparência personalizada, mantém-se o preview legado e os controles
  ficam desabilitados. Assim a representação da tecla sem `appearance` não é
  convertida implicitamente para outra configuração.
- O hit-test da v6 permanece geométrico e aproximado. Os canais RGBA são
  produzidos separadamente para futura seleção pelo alfa, mas a v7 **não**
  promete seleção pixel a pixel nem muda o comportamento dos gestos.
- O modo `none` mantém a cor de fundo definida na aparência, não produz
  um LCD desligado.

## Instalação e validação

1. Abra **Vision 02 — Atualizações**, selecione o ZIP `vision02-camadas-v7-update.zip`.
2. Clique em **Inspecionar atualização** e depois **Aplicar e testar**.
   O gerenciador valida hashes SHA-256, cria backup e executa a suíte completa.
3. Feche/reabra **Vision 02 Studio** pelo menu do Ubuntu.
4. Em **Teclas → Composição**, selecione uma tecla com aparência personalizada,
   ícone e texto. Desmarque **Exibir pixels da Imagem (prévia)** e depois
   **Exibir pixels do Texto (prévia)**; confirme as quatro combinações.
5. Confira que a miniatura na aba Imagem permanece completa e que movimentação,
   zoom, molduras, bloqueio, desfazer/refazer e salvamento explícito continuam
   funcionando. Para não alterar seu perfil pessoal, não clique em Salvar.

As modificações no `examples/profiles/desenvolvimento-switch.yaml`, scripts de
diagnóstico, credenciais OBS, IPC, systemd e USB/HID ficam fora do pacote.

## Atualização via Git

O gerenciador altera os arquivos do checkout, mas **não cria commits**. Após
confirmar o GTK, inclua somente os seis arquivos da v7 no commit Git, sem
incluir o perfil YAML ou scripts de diagnóstico.
