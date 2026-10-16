# Galeria visual de ícones no Vision 02 Studio

Na seção **Teclas**, selecione uma tecla e abra a **Galeria visual de ícones**.

- Pesquise pelo nome (sem diferenciar maiúsculas e acentos). A grade mostra até 90 miniaturas de cada vez; refine a pesquisa para mais resultados.
- Clique uma vez na imagem para preencher o campo **Imagem** e iniciar uma pré-visualização **local**.
- Para importar PNG, JPEG ou WebP, use **Importar imagem para a galeria…**. O arquivo passa pelo importador já existente (PNG RGB 100 × 100, limite de tamanho e deduplicação) antes de entrar na biblioteca pessoal.
- Para alterar o controlador, confirme a aparência, clique em **Salvar YAML com backup** e somente depois em **Aplicar ao dispositivo (IPC)**.
- A página **Ícones** e o editor avançado continuam disponíveis.

A galeria nunca abre o dispositivo USB, não executa ações, não altera o YAML ao selecionar miniaturas e não exibe credenciais OBS. O painel não duplica o importador de ícones nem o mecanismo de gravação dos perfis.

**Testes:** `python -m pytest -q tests/test_studio_icon_gallery.py` e suíte completa. A apresentação GTK deve ser validada manualmente na sessão Ubuntu do usuário.
