# Personalização visual dos displays — Vision 02

O editor GTK4 oferece **Aparência avançada** para cada tecla configurada. O resultado da prévia é gerado pelo mesmo módulo `vision02.rendering` que entrega a imagem ao codificador JPEG/HID. As 15 posições físicas e o mapeamento para os displays não mudam.

## Uso

1. Abra `./scripts/vision02-editor`, selecione o perfil e a tecla física.
2. Expanda **Aparência avançada (texto, cores e posição)** e marque **Usar aparência personalizada nesta tecla**.
3. Configure fundo `#RRGGBB`, texto, fonte Sans/Serif/Mono, tamanho 8–36, peso, alinhamentos horizontal/vertical, deslocamentos X/Y e ajuste da imagem.
4. A **Prévia visual da tecla** é atualizada automaticamente após breve intervalo, sem alterar o YAML ou acessar o hardware. Também é possível usar **Pré-visualizar** para atualizar a grade de 15 teclas.
5. Clique em **Salvar YAML**. Só então clique em **Aplicar ao dispositivo** (IPC reload sem reiniciar o serviço).

Se o campo **Imagem** estiver preenchido, ela vira o fundo da composição visual. Ajuste: **Preencher** (corte central), **Conter** (preserva proporção e adiciona bordas) ou **Esticar**. Marque **Exibir texto sobre o fundo/imagem** para sobrepor o título. O campo **Texto visual** vazio utiliza o rótulo da tecla. Para ocultar o texto, desmarque essa opção.

## YAML e retrocompatibilidade

Um perfil permanece na `version: 1` e as teclas sem `appearance` usam o renderizador anterior, inclusive o comportamento de imagens personalizadas sem sobreposição de texto.

```yaml
version: 1
name: Trabalho
keys:
  1:
    label: Grafana
    image: /home/usuario/.local/share/vision02/assets/icons/exemplo.png
    appearance:
      background: '#081016'
      text: Métricas
      font_family: sans
      font_size: 16
      font_weight: bold
      text_color: '#FFFFFF'
      horizontal: center
      vertical: bottom
      offset_x: 0
      offset_y: -6
      image_fit: cover
      show_text: true
    action:
      type: url
      url: https://grafana.com
```

`appearance` é opcional. São aceitos somente os nomes de campos documentados. Valores inválidos, como cores sem `#RRGGBB`, fontes desconhecidas ou deslocamentos além de ±40 px, bloqueiam o salvamento e o reload; a configuração antiga permanece. O campo `text` permite até 120 caracteres. Fonte e cores dependem do ambiente local usado para renderizar os PNG.

## Arquitetura e limites

- `models.py`/`loader.py`: modelo e validação YAML (`KeyAppearance`).
- `rendering.py`: composição PIL em RGB 100 × 100; tanto GUI quanto controlador utilizam esse mesmo resultado.
- `vision02_editor_backend.py`: comando `style-preview` (somente imagem), `preview` (15 teclas) e `save` (backup, verificação SHA e gravação atômica).
- `vision02_editor.py`: controles GTK e prévia local com debounce.
- O controlador ainda aplica rotação de 180° e compressão JPEG no estágio `encode_image`; a prévia é o RGB **antes** desse estágio. Pequenas diferenças de compressão e da calibração do LCD são esperadas.
- A atualização do código Python em execução requer **um reinício inicial** do `vision02.service`, depois da aprovação dos testes. Edições posteriores são aplicadas por IPC sem reiniciar.
- O editor não cria nem altera arquivos de imagem da biblioteca ao aplicar estilo, e não executa ações ou acessa USB/HID.
