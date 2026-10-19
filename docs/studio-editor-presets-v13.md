# Vision 02 Studio v13 — Área de trabalho interativa de presets

A v13 complementa a edição segura de presets da v12, sem modificar o renderizador do LCD, os perfis YAML, o IPC, o controlador HID ou o serviço `vision02.service`.

## Localização na interface

**Teclas → Imagem → Biblioteca de presets visuais → Editor visual de presets (v12) → Área de trabalho interativa (v13)**.

1. Na galeria, selecione um preset existente e clique em **Carregar preset selecionado para edição**.
2. A prévia ampliada possui área de trabalho de **320 × 320 pixels** e zoom **100% / 150% / 200%**. O zoom apenas amplia/recorta a prévia local: não altera a imagem salva.
3. Clique sobre a **Imagem** ou o **Texto** para selecioná-lo; em sobreposição, o seletor **Elemento: Imagem / Texto** determina a prioridade. O contorno ciano indica Imagem; o âmbar indica Texto.
4. Arraste a seleção para mover. A alça quadrada no canto inferior direito da imagem permite alterar sua escala. Somente imagens possuem alça de redimensionamento.
5. **Encaixe inteligente** ativa aproximação de guias centrais/laterais. Desative para posicionar sem encaixe. Todas as operações respeitam os limites originais: imagem X/Y `-100..100`, texto X/Y `-40..40`, escala `25..200`.
6. Cada gesto concluído corresponde a **uma entrada** do histórico já existente da v12. **Desfazer** / **Refazer** também atualizam os controles numéricos.
7. Os contornos respondem durante o arraste; a nova imagem rasterizada é gerada pelo backend da v12 após o fim do gesto (pequena pausa). O movimento não salva o preset.
8. Clique em **Salvar alterações no preset** para persistir com backup/revisão SHA-256 ou em **Salvar como novo preset** para preservar o original. Essas operações seguem todas as proteções da v12.

## Limitações conscientes

- A seleção no **editor de presets** é geométrica e aproximada, reutilizando `studio_visual_selection`. A camada de seleção pixel-a-pixel da v8 pertence ao editor de teclas e não é aplicada automaticamente neste canvas.
- Como a prévia gerada pela v12 é um PNG composto, os pixels da imagem rasterizada só refletem novos valores quando o backend retorna a prévia. O contorno de seleção acompanha o gesto imediatamente.
- Clique no fundo fora dos elementos não inicia transformação. Elementos superpostos podem ser escolhidos explicitamente pelo seletor acima da área.
- A interface v13 requer verificação visual em **GTK4/Wayland ou X11** no Ubuntu do usuário. Os testes automatizados locais validam o modelo matemático e a presença dos pontos de integração; não substituem um teste de interação real.
- Os estados de zoom e elemento ativo são locais, não persistidos.

## Segurança

- O módulo `studio_preset_canvas_v13.py` só calcula geometria, seleção e transformações de um **dicionário em memória**.
- O backend existente da v12 é o único responsável por validar, pré-visualizar e salvar presets. A v13 não cria novo endpoint de escrita.
- As quatro abas Ação / Imagem / Texto / Composição e a Biblioteca da v10/v11 continuam disponíveis.
- Nenhuma operação no canvas edita perfis YAML, envia IPC, altera ações/credenciais OBS, reinicia serviços ou comunica-se com o dispositivo USB/HID.

## Teste manual (sem alterar o hardware)

1. Escolha um preset de teste que tenha imagem e texto, carregue-o no editor.
2. Expanda **Área de trabalho interativa (v13)**, selecione **Imagem**, arraste e redimensione pela alça quadrada; verifique os campos `Imagem X/Y` e `Escala`.
3. Escolha **Texto**, arraste; confira `Texto X/Y`.
4. Teste 100%, 150%, 200%, habilite/desabilite o encaixe, use **Desfazer** e **Refazer**.
5. Informe um nome novo e clique em **Salvar como novo preset**. Verifique que o original continua intacto.
6. Não clique em **Aplicar preset e salvar YAML com backup** ou **Aplicar ao dispositivo (IPC)**.

## Testes

`cd ~/projetos/rise-mode-vision02/rise-mode-vision02-linux && .venv/bin/python -m pytest -q`

Base v12: **1.453 testes**. A v13 adiciona **40 testes**; referência após instalação: **1.493 testes**.
