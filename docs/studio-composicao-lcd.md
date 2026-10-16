# Vision 02 Studio — composição visual livre dos LCDs

A versão implementa **arrasto de texto e imagem** em uma tela ampliada de 240 × 240 px que representa o LCD físico de 100 × 100 px. O usuário deve selecionar a tecla na seção **Teclas**, ativar **Usar aparência personalizada**, abrir **Composição — arrastar texto ou imagem** e gerar uma primeira **Pré-visualizar (local)**. Em seguida, escolha `Imagem` ou `Texto` e arraste na tela. A marcação **Encaixar na grade de 5 pixels** é opcional.

## Novos parâmetros YAML

Dentro do objeto opcional `appearance` de uma tecla:

```yaml
appearance:
  image_x: 12          # -100 a 100 px, positivo à direita
  image_y: -8          # -100 a 100 px, positivo para baixo
  image_scale: 80      # 25% a 200% da imagem ajustada
  image_fit: contain   # cover, contain, stretch
  offset_x: 8          # -40 a 40 px do texto
  offset_y: -12        # -40 a 40 px do texto
```

O ícone primeiro é normalizado com `image_fit` para a área de 100 × 100, depois escalado proporcionalmente e posicionado em relação ao centro do LCD; o excedente é recortado. A composição mantém transparência e usa o mesmo renderizador no serviço e no backend de prévia. Valores ausentes equivalem a `image_x = 0`, `image_y = 0`, `image_scale = 100`, mantendo a rasterização dos perfis anteriores. **Aparência ausente** preserva a renderização legada.

Texto e imagem podem ocupar a mesma área: a imagem é desenhada primeiro e o texto por cima. A grade serve apenas como guia visual e não faz parte da imagem enviada ao LCD. O arrasto não grava o YAML nem altera o hardware; a prévia é regenerada após a alteração. **Salvar YAML com backup** e **Aplicar ao dispositivo (IPC)** são operações explícitas, separadas.

## Limites e compatibilidade

- Arrasto atua em apenas um elemento por vez, escolhido na lista `Imagem` / `Texto`; não executa ações das teclas.
- Deslocamentos do texto preservam os limites históricos de ±40 px. A imagem admite deslocamentos de ±100 px e escala de 25–200%.
- Imagens podem ser parcialmente ou completamente recortadas na borda do LCD; use os controles numéricos para recuperá-las.
- A interface não abre uma segunda conexão HID, não modifica o serviço systemd e não altera perfis pessoais durante a instalação.
- A renderização de prévia acontece no backend já existente com validação e gravação condicional por SHA-256; a GUI não grava YAML diretamente.
