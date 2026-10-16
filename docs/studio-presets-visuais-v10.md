# Vision 02 Studio v10 — Biblioteca de presets visuais

## Objetivo

A v10 cria uma **biblioteca local de aparências** a partir das teclas já salvas,
sem armazenar nem copiar ações, rótulos, parâmetros OBS ou credenciais. Um preset
contém somente os campos `image` e `appearance` (incluindo `appearance.text`,
quando explicitamente definido). Ações das teclas de destino permanecem intactas.

A interface mantém as abas **Ação / Imagem / Texto / Composição**. Abra
**Teclas → Imagem → Biblioteca de presets visuais (v10)**.

## Criar e usar

1. Escolha um perfil e uma tecla configurada com imagem/estilo que você deseja
   reutilizar. **Salve ou descarte edições pendentes** primeiro: o preset sempre
   parte da aparência já salva no YAML.
2. Expanda **Biblioteca de presets visuais (v10)**, digite um nome, por exemplo
   `OBS Azul`, e clique em **Salvar aparência da tecla como preset**.
3. Selecione o preset na lista e clique em **Pré-visualizar preset (local)**.
   A prévia usa o rótulo da tecla atual se o estilo não possuir texto próprio;
   isso não grava YAML e não atualiza o LCD.
4. Marque uma ou várias teclas configuradas como destinos, marque a confirmação
   e clique em **Aplicar preset e salvar YAML com backup**. A operação grava o
   YAML uma única vez após validar o conteúdo e verificar o SHA da versão lida.
5. Somente se quiser refletir a mudança no hardware, clique separadamente em
   **Aplicar ao dispositivo (IPC)**.

A biblioteca também oferece **Renomear**, **Excluir**, **Exportar ZIP…** e
**Importar ZIP…**. A exclusão é confirmada em um diálogo e não remove os assets
persistentes já aplicados aos perfis. Na importação, um nome/identificador que
já existe é recusado em vez de substituir o preset silenciosamente. Para
renomear, selecione o preset, digite o novo nome e pressione **Renomear**.

## Armazenamento

- `~/.config/vision02/presets/<id>.json` — dados do estilo sem ações e rótulos.
- `~/.config/vision02/presets/<id>.png` — cópia PNG da imagem, quando presente.
- `~/.local/share/vision02/preset-assets/<sha256>.png` — imagem imutável,
  copiada ao aplicar o preset. Isso permite excluir um preset sem quebrar as
  teclas cujas aparências já foram aplicadas.
- `~/.local/state/vision02/editor-backups/` — YAML original salvo antes de cada
  aplicação; o prefixo `-preset-v10-` identifica esses backups.

As raízes usam `XDG_CONFIG_HOME`, `XDG_DATA_HOME` e `XDG_STATE_HOME` quando
configuradas. Diretórios são privados (`0700`) e arquivos novos (`0600`).

## Formato de exportação

ZIP contendo **apenas** `preset.json` e, opcionalmente, `image.png`. A imagem
PNG e o manifesto contêm verificação SHA-256. Não há scripts, YAML, credenciais
ou ações executáveis no formato. A importação recusa caminhos adicionais ou
conteúdo não conforme. A exportação pede um **nome de arquivo novo** (`.zip`),
sem sobrescrever arquivos existentes.

Limites: imagem de até 5 MiB e até 4 milhões de pixels, pacote de até 6 MiB.

## Segurança e compatibilidade

- Apenas teclas já configuradas no **mesmo perfil** podem receber o preset.
- As ações `action`, os rótulos `label`, o serviço systemd e o controlador HID
  nunca são modificados diretamente por criação, prévia ou importação/exportação.
- Uma aparência aplicada pode conter caminho absoluto para o asset privado
  `preset-assets/<sha>.png`. Os arquivos são acessíveis ao usuário que instalou
  o preset; para transferir entre máquinas, exporte e importe o ZIP.
- A aplicação não executa IPC automaticamente, mas salva o YAML do perfil após
  confirmação explícita. O YAML poderá ser reformatado sem modificar as ações.
- A gravação usa arquivo temporário no diretório do perfil, verifica alterações
  concorrentes e mantém o original em backup antes da substituição atômica.
- Não existe *undo* de múltiplas gravações YAML pelo histórico de composição:
  para desfazer uma aplicação, use o backup do YAML ou restaure o arquivo
  deliberadamente. O Gerenciador de Atualizações só restaura **arquivos de código**
  e não executa restauração de perfis pessoais automaticamente.

## Validação manual

Em um **perfil de desenvolvimento**: crie um preset da tecla 01, selecione
tecla 02 com ação diferente, visualize, aplique e confira a imagem, as cores,
o texto visual e a ação da tecla 02. Renomeie e exporte o preset, depois exclua
o preset da biblioteca e confirme que a imagem da tecla 02 continua acessível.
Experimente importar o ZIP depois de excluir o preset. Os pixels do LCD não
mudam enquanto o IPC não for acionado explicitamente.

A atualização inclui testes de armazenamento, integridade dos ZIPs, validação
de perfil, SHA concorrente, ações preservadas, importação/exportação e integração
com o backend JSON.
