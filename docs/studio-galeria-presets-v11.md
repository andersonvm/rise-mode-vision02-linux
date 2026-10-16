# Vision 02 Studio v11 — Galeria visual de presets

A v11 amplia a **Biblioteca de presets visuais (v10)**, localizada na aba
**Teclas → Imagem**. As quatro abas existentes — Ação, Imagem, Texto e Composição —
permanecem inalteradas.

## Novidades

- Miniaturas de 100 × 100 geradas pelo renderizador local, com cache XDG.
- Pesquisa de nomes e categorias (sem diferenciar maiúsculas/minúsculas).
- Filtro **Só favoritos** e filtro por categoria.
- Favoritar/desfavoritar o preset selecionado.
- Categorizar e duplicar um preset, mantendo a imagem e a aparência.
- Clique numa miniatura seleciona o mesmo preset na interface da v10; a confirmação
  anterior de aplicação em lote é cancelada.
- A aplicação de presets às teclas continua usando o botão da v10 **Aplicar
  preset e salvar YAML com backup**, que exige seleção dos destinos e confirmação.

## Como testar

1. Instale pelo **Vision 02 — Atualizações**, com **Inspecionar atualização** e
   **Aplicar e testar**. A expectativa é **1.416 testes**.
2. Reinicie o Studio; abra **Teclas → Imagem → Biblioteca de presets visuais (v10) · galeria v11**.
3. Crie dois presets de teste usando a v10 (se ainda não tiver presets salvos).
4. Observe as miniaturas e pesquise parte do nome.
5. Clique no cartão de um preset, clique em **Marcar como favorito**, marque
   **Só favoritos** e confirme que o outro preset desaparece do filtro.
6. Defina uma categoria, por exemplo `OBS`, e clique em **Salvar categoria**.
7. Use **Filtrar categoria** para mostrar apenas o preset categorizado.
8. Insira um nome ainda não usado e clique em **Duplicar preset**; remova os
   filtros para ver a cópia. A cópia preserva o estilo e a imagem, mas começa
   sem a marca de favorito.
9. Clique no cartão e confirme que o DropDown antigo aponta ao mesmo preset.
   A prévia local e a aplicação em lote continuam disponíveis, sem IPC automático.

## Armazenamento e compatibilidade

- Os manifestos da v10, armazenados em `~/.config/vision02/presets`, não são
  alterados pelos favoritos nem pelas categorias.
- Metadados da galeria: `$XDG_CONFIG_HOME/vision02/preset-gallery-v11.json`
  (padrão `~/.config/vision02/preset-gallery-v11.json`, arquivo `0600`).
- Miniaturas descartáveis: `$XDG_CACHE_HOME/vision02/preset-gallery-v11/`.
- Duplicatas utilizam a mesma validação do modelo de presets da v10, sem
  copiar ações, rótulos, comandos ou credenciais OBS.
- O ZIP exportado da v10 **não inclui favoritos ou categorias**; eles são
  preferências locais, não dados de aparência portáveis.
- A miniatura usa o texto **Prévia** como rótulo demonstrativo quando o preset
  não tem texto próprio; a imagem final de cada tecla continuará usando as
  regras do renderizador e o rótulo do perfil de destino.
- Um preset com manifesto ou PNG corrompido não é incluído na galeria; o
  registro original permanece no disco para inspeção.
- Não há reordenação real das camadas nem acesso USB/HID pelo editor.

## Segurança

Este pacote não modifica perfis pessoais YAML, `vision02.service`, arquivos
USB/HID ou segredos OBS. Atualizar favoritos, categorias e duplicar presets
não executa o botão **Aplicar ao dispositivo (IPC)**.
