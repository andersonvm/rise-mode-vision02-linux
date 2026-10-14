# Recarregamento dinâmico dos perfis Vision 02

Depois de **salvar** alterações com o editor GTK, use **Aplicar ao dispositivo**
ou execute `.venv/bin/vision02 control reload` no terminal.

O controlador valida **todos** os perfis YAML configurados antes de alterar
qualquer estado, mantém o perfil ativo e prepara as imagens sem tocar no USB.
Em seguida suspende o despacho de novas ações, aguarda a fila de ações terminar,
atualiza os LCDs na thread proprietária do HID e descarta eventos antigos.
Somente após sucesso aceita os novos mapeamentos de teclas.

Erros de YAML, destinos ou renderização preservam a configuração que já estava
em execução. Se a transmissão HID falhar, a sessão é encerrada e recuperada
pelo supervisor hotplug; alguns LCDs podem ter recebido atualização parcial.

O reload não adiciona/remove nomes dinamicamente se o nome do perfil **ativo**
foi removido; nesse caso, selecione um perfil que permaneça antes de recarregar.

A instalação inicial desta funcionalidade exige reiniciar `vision02.service`
**uma vez** para carregar o novo código; após isso, editar/aplicar não reinicia.
`status` e `profiles` continuam funcionando normalmente.

**Limitação**: o painel GTK em execução pode precisar ser reaberto para
atualizar os ícones pré-renderizados da visualização após salvar o YAML.
