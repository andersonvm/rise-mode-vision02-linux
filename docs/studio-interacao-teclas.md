# Correção de seleção e atividade das teclas no Vision 02 Studio

- O clique simples seleciona a tecla e atualiza apenas o destaque e os detalhes.
- O clique duplo é reconhecido pelo evento `clicked` do `Gtk.Button`, sem disputar o gesto interno do widget nem recriar os filhos do botão durante o primeiro clique.
- A atividade HID recebe CSS próprio de borda amarela, texto `PRESSIONADA`/`RECENTE` na tecla e um diagnóstico legível abaixo da grade.
- A janela consulta a atividade apenas pelo IPC. Não acessa USB/HID diretamente.

## Teste no Ubuntu

Após aplicar a atualização, feche e reabra `./scripts/vision02-studio`. Na aba Teclas, clique uma vez numa tecla para selecioná-la e duas vezes rapidamente para abrir o editor naquela tecla. Pressione uma tecla física comum (sem troca de perfil): ela deve exibir `PRESSIONADA` e depois `RECENTE` por um instante. Se nada aparecer, reinicie o serviço uma vez para garantir que o comando IPC `key_activity` esteja disponível. Consulte também `.venv/bin/vision02 control key_activity` imediatamente após pressionar uma tecla física.
