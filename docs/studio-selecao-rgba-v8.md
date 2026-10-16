# Vision 02 Studio — seleção por máscaras RGBA v8

A v8 melhora a seleção local no preview em **Teclas → Composição**. Em teclas
com aparência personalizada, a seleção considera apenas pixels opacos dos
canais **Imagem** e **Texto** gerados na prévia local da v7.

## Funcionamento

1. Ao obter uma prévia atualizada, o backend da v7 devolve os PNGs RGBA da
   imagem e do texto; a v8 os lê com `GdkPixbuf` (Python do sistema).
2. Os canais alfa são convertidos para máscaras em RAM de 100 × 100 bytes.
   Uma camada só é selecionável em um pixel quando alfa ≥ **32/255**.
3. O clique do GTK é transformado para coordenadas do LCD virtual 100 × 100,
   respeitando a ampliação centralizada de 100%, 150% ou 200%.
4. Quando os dois canais têm alfa sob o clique, a preferência explícita da v3
   decide qual selecionar. O botão **Alternar camada no último ponto
   sobreposto** usa o mesmo teste de pixels.
5. Os controles **Exibir pixels ... (prévia)** da v7 também controlam quais
   canais podem ser selecionados. Uma camada oculta não recebe novos cliques.
6. As molduras passam a delimitar o conteúdo opaco da camada, em vez de
   somente a região geométrica estimada.

Quando os PNGs RGBA não estão disponíveis ou são inválidos (por exemplo,
perfil legado), permanece a **seleção geométrica da v3**. A interface informa
qual mecanismo está ativo. Máscaras são invalidadas quando o formulário muda,
para não selecionar pixels da prévia anterior, e são recalculadas quando a
pré-visualização atualizada chega.

## Limites

- Este é um recurso **somente da interface de edição**. O LCD mantém o mesmo
  renderizador, ordem imagem → texto e saída normal.
- Molduras são caixas de contorno dos pixels não transparentes; em formatos
  irregulares a caixa inclui áreas vazias, embora **cliques em áreas vazias não
  selecionem a camada**.
- Por desempenho, o limiar mínimo evita selecionar vestígios quase invisíveis
  de antialiasing. Para perfis sem aparência personalizada ou até a conclusão
  de uma prévia, a seleção mantém o fallback geométrico.
- Deslocar a imagem ou texto invalida as máscaras até que a nova prévia seja
  gerada; durante essa janela o editor pode recorrer à geometria aproximada.
- A detecção de versão do Gerenciador de Atualizações v1.1 ainda pode mostrar
  “v7” após instalar a v8. O commit Git e o histórico de atualização indicam
  a alteração instalada; o detector gráfico será aprimorado separadamente.

## Verificação manual no Ubuntu / GTK4

1. Feche o Studio, instale a v8 pelo Gerenciador e reabra-o.
2. Em **Teclas → Composição**, selecione uma tecla com **aparência
   personalizada**, ícone PNG com transparência e texto.
3. Espere a mensagem **Seleção v8: pixels RGBA visíveis**; clique em uma
   região transparente interna da imagem. A imagem **não deve** ser escolhida
   por esse clique, salvo se o texto for opaco ali.
4. Clique em um pixel visível da imagem: a seleção deve ir para **Imagem**.
5. Clique em uma letra: deve selecionar **Texto**. Na sobreposição, teste a
   preferência de imagem e **Alternar camada no último ponto sobreposto**.
6. Teste com zoom de 100%, 150% e 200% e com ambos os controles de
   visibilidade da v7.
7. Mova ou redimensione os elementos: o movimento, Undo/Redo e a prévia
   continuam funcionando. A máscara será atualizada depois da prévia local.
8. Não salve nem use **Aplicar ao dispositivo (IPC)** durante o teste. Se
   houver alterações geométricas, descarte/recarregue ao final.

## Testes e segurança

O pacote da v8 adiciona o módulo puro `studio_alpha_hit_v8.py`, adapta
`apps/vision02_studio.py` e inclui `tests/test_studio_alpha_hit_v8.py`.
Nenhum arquivo de perfis, chave, credencial OBS, USB/HID, service unit ou
renderizador do dispositivo faz parte da atualização.

O ZIP contém um `manifest.json` no formato
`vision02-studio-update/v1`, com hashes de origem e destino. O gerenciador
1.1 valida os arquivos antes de atualizar, cria backup, roda toda a suíte
com o Python da `.venv` e tenta rollback caso a validação falhe.
