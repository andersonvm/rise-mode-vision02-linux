# Vision 02 Studio — Aparência em lote v9

## Objetivo

Reaproveitar a **aparência salva** de uma tecla em outras teclas **já configuradas
no mesmo perfil**, sem copiar ações e sem executar operações no hardware.

A cópia inclui somente os campos YAML `image` e `appearance` (cores, fonte,
posicionamento, escala e `appearance.text`, quando houver). Não altera `label`,
`action`, argumentos de comandos, atalhos, ações de perfil ou parâmetros OBS.
Se a origem não contiver imagem ou aparência personalizada, o campo correspondente
é removido dos destinos. O texto visual herdado do rótulo continua herdando o
rótulo **do destino**.

## Operação no Ubuntu

1. Abra **Vision 02 Studio → Teclas** e selecione o perfil desejado.
2. Selecione uma tecla de origem **já configurada e salva**. Caso tenha alterações
   pendentes, salve ou descarte antes de continuar.
3. Abra a aba **Imagem** e expanda **Copiar aparência para outras teclas (lote)**.
4. Clique em **Copiar aparência salva da tecla atual**. Isso não grava nada.
5. Marque uma ou várias teclas de destino. Teclas não configuradas e a origem
   ficam desabilitadas.
6. Marque **Confirmo a substituição da aparência...** e clique em
   **Aplicar em lote e salvar YAML com backup**.
7. Aguarde o resultado. A alteração é feita em **uma única gravação** do YAML,
   com **um backup**. Se o arquivo mudar no disco durante a edição, a operação
   será recusada.
8. Para atualizar os LCDs físicos, utilize separadamente
   **Aplicar ao dispositivo (IPC)**. A cópia não envia comandos USB/HID nem IPC.

O backend valida o YAML no mesmo diretório do perfil (preservando caminhos
relativos das imagens), testa a integridade antes da substituição, preserva as
permissões e guarda o YAML original em
`~/.local/state/vision02/editor-backups/` (ou `$XDG_STATE_HOME/vision02/editor-backups/`).

## Limites deliberados

- Escopo: **somente o perfil atual**, 15 teclas físicas no máximo.
- Somente destinos com ação configurada; teclas vazias não são criadas.
- Origem salva no disco: não copia alterações ainda não salvas no formulário.
- Cópia de rótulo e ação não é suportada por esta operação.
- Não oferece clipboard global do sistema ou transferência entre perfis.
- O arquivo YAML pode ser reformatado por `yaml.safe_dump`, mas o conteúdo
  semântico de ações, rótulos e demais campos das teclas é preservado.
- Não salva cópias automáticas no Git e não altera serviços systemd.

## Validar

O pacote v9 adiciona 61 testes automatizados relativos à cópia em lote.
O instalador gráfico deve executar a suíte completa antes de confirmar a
atualização; verifique a contagem na sua instalação. Em caso de falha, o
Gerenciador tenta retornar os arquivos de código à versão anterior. O backup
YAML das aparências copiadas é uma operação separada dentro do Studio.
