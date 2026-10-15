# Vision 02 — três perfis especializados OBS

Abrir: `./scripts/vision02-obs-profiles` (ou o botão no painel OBS).

A interface consulta o OBS WebSocket local e mostra as cenas reais e as entradas de áudio existentes. Selecione até **14 cenas** e até **12 entradas**, clique **Criar os três perfis** e, depois, **Aplicar ao dispositivo (IPC)**.

O comando não executa gravação, transmissão nem outras ações no OBS. As operações só são executadas quando a tecla física é pressionada.

- **OBS — Controle:** gravação, pausa, transmissão, microfone, desktop, câmera virtual, navegação de cenas, replay, captura, status, atalhos para Cenas/Áudio e Sistema.
- **OBS — Cenas:** 01–14 são cenas vinculadas por nome exato; 15 retorna ao Controle.
- **OBS — Áudio:** 01–12 são entradas escolhidas (mute); 13 Cenas, 14 Controle, 15 Sistema.

O perfil original **OBS Studio** não é modificado. Se ele existir, Controle terá um atalho para ele na tecla 14.

Os arquivos são gerados em `~/.config/vision02/profiles/`: `obs-controle.yaml`, `obs-cenas.yaml`, `obs-audio.yaml`. Se algum nome ou arquivo já existir, o comando **interrompe sem sobrescrever**. Para editar posteriormente, utilize o editor visual genérico e o gerenciamento existente; não execute o criador novamente sobre os mesmos arquivos.

A criação valida todos os YAML e as referências de navegação no catálogo completo. A configuração pessoal `obs.json` com a senha não é acessada pelo criador, exceto para consultar o OBS durante a descoberta. O script não reinicia o serviço, não executa `sudo` e não acessa diretamente o USB/HID.

A tecla de **transmissão ao vivo** pode iniciar uma live real. Use apenas quando estiver preparado.

O estado das entradas selecionadas é consultado pelo OBS WebSocket; o controlador permanece a única thread responsável pelas escritas HID. O monitoramento OBS consulta no máximo 32 entradas a cada ciclo, com tolerância a fontes sem suporte a mute.
