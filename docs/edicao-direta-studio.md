# Edição direta e indicação de tecla pressionada

Versão do Studio com seleção direta das teclas e consulta IPC de atividade.

- **Clique simples** seleciona a tecla na grade 5×3 e permite inspecionar o LCD.
- **Editar tecla selecionada** abre `vision02-editor --profile "<perfil ativo>" --key N`.
- **Clique duplo** abre a mesma edição diretamente. A GUI **não executa a ação** da tecla.
- Se o editor já estiver aberto, o comando de linha é encaminhado à instância GTK existente. Edições não salvas não são descartadas.
- As teclas físicas pressionadas recebem destaque no Studio via IPC `key_activity` durante a seção **Teclas**, sem novo leitor HID nem controle remoto de ações.
- A indicação recente expira aproximadamente 1,8 s após a última pressão; não é uma confirmação de execução da ação.
- A CLI `vision02 control key_activity` retorna `pressed_keys`, `last_key` e `sequence`.
- Salvamento e aplicação continuam sendo feitos no editor (backup do YAML e recarregamento IPC).
- A consulta é somente leitura; não abre nem interrompe o USB.

Após instalar o código, reinicie o serviço **uma única vez** para carregar o novo comando IPC; alterações futuras de teclas seguem sem reinício.
