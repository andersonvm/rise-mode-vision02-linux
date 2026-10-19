# Vision 02 Studio v12 — Editor visual de presets

O editor de presets fica em **Teclas → Imagem → Biblioteca de presets visuais → Editor visual de presets (v12)**. A v12 preserva o editor de quatro abas (Ação, Imagem, Texto e Composição), a biblioteca v10, a galeria v11 e a aplicação em lote.

## Fluxo de edição

1. Selecione um preset na galeria v11 ou no seletor v10.
2. Expanda **Editor visual de presets (v12)** e clique em **Carregar preset selecionado para edição**.
3. Modifique fundo, texto, fonte (`sans`, `serif`, `mono`), peso (`regular`, `bold`), cores `#RRGGBB`, alinhamento, deslocamentos, posição/escala da imagem, exibição de texto e/ou caminho de imagem.
4. A prévia local de **100 × 100 pixels** é atualizada após uma breve pausa. Não salva YAML nem envia comandos ao dispositivo. Erros de validação aparecem no estado do editor.
5. Use **Desfazer** e **Refazer** para as alterações do rascunho. O histórico contém até 100 revisões recentes e não depende do histórico de movimentação das teclas.
6. Clique em **Salvar alterações no preset** para substituir os dados **desse preset** após verificação de revisão SHA-256. O editor cria uma cópia de segurança local de seu manifesto/imagem anterior.
7. Ou informe outro nome em **Novo nome para Salvar como…** e clique em **Salvar como novo preset** para criar uma cópia, preservando o preset anterior. Nomes duplicados são recusados.
8. Os cartões da galeria são atualizados após a gravação. Recarregue um preset caso o estado no disco mude fora do editor.

> **Carregar** outro preset com alterações pendentes solicitará confirmação de descarte. Alterar a seleção na galeria apenas desativa os botões de salvamento até que o rascunho correspondente volte a ser selecionado.

## Limites e segurança

- O formulário oferece todos os campos do modelo `KeyAppearance`; as combinações e intervalos são os de `parse_appearance`, sem coerção de tipos.
- O texto vazio significa herdar o rótulo da tecla na renderização final; a miniatura usa o texto demonstrativo `Prévia` se necessário.
- A imagem escolhida é convertida/validada pela biblioteca da v10 antes de salvar. Arquivos inexistentes, links simbólicos e imagens excessivamente grandes são recusados. Deixar o campo de imagem vazio remove-a **somente do preset depois de clicar em Salvar**.
- A edição preserva `id`/nome do preset existente; renomeação permanece no comando v10 **Renomear**. `Salvar como` usa um novo nome e identificador.
- Favoritos e categorias da v11 são mantidos por identificador no **Salvar**. Uma cópia criada com **Salvar como** começa sem favorito/categoria; isso é proposital.
- `Salvar` verifica uma revisão do conteúdo do preset e bloqueia edições concorrentes desatualizadas. Os dados originais são copiados em `~/.config/vision02/presets/.editor-v12-backups/` ou `$XDG_CONFIG_HOME/vision02/presets/.editor-v12-backups/` antes de substituir.
- O formato v10 usa arquivos `id.json` e `id.png` separados, portanto não existe atomicidade entre os dois na perda abrupta de energia. A v12 restaura os dois ao detectar exceções normais na gravação e preserva a cópia de segurança para recuperação manual após incidentes.
- Nenhum botão v12 grava perfis YAML, altera ações, rótulos, credenciais OBS, envia IPC ou reinicia `vision02.service`.

## Teste manual sem afetar as teclas físicas

1. Crie um preset de teste na biblioteca v10, se necessário.
2. Carregue o preset na v12, altere **Fundo** para `#225588`, depois o **Tamanho da fonte**.
3. Observe a prévia; use **Desfazer** e **Refazer** para confirmar as mudanças.
4. Escolha outra imagem local e teste **Remover imagem do rascunho**. Até salvar, o preset original permanece intacto.
5. Informe `Preset v12 Teste` e clique em **Salvar como novo preset**. Verifique a cópia na galeria e que o original não mudou.
6. Carregue a nova cópia, modifique um campo e clique em **Salvar alterações no preset**. Confira que a miniatura muda; opcionalmente exporte a cópia pelo ZIP v10.
7. Não clique em **Aplicar preset e salvar YAML com backup** nem em **Aplicar ao dispositivo (IPC)** neste teste.

## Validação automatizada

O pacote acrescenta `tests/test_studio_preset_editor_v12.py`; execute `.venv/bin/python -m pytest -q` no repositório. A contagem de referência é **1.452 testes** (1.416 anteriores + 36 novos).
