# Vision 02 Studio v15 — Menu de Perfis integrado

## Objetivo

O **Menu de Perfis** passa a ser administrado diretamente pela barra lateral do Vision 02 Studio, sem abrir um aplicativo separado. A tecla física **15** de cada perfil continua voltando ao menu; as teclas **1–14** não são modificadas.

A implementação reutiliza o formato, os ícones, o bloqueio do catálogo, os backups e a restauração do **Vision 02 — Menu de Perfis v1.0**, instalado anteriormente. Ambos gerenciam os mesmos perfis pessoais (não se criam menus paralelos).

## Como usar

1. Abra o Vision 02 Studio e selecione **Menu de Perfis** na barra lateral. A seção **Perfis** também possui um atalho para essa página.
2. Clique em **Inspecionar catálogo** para ver os nomes encontrados, função atual da tecla 15, páginas e arquivos pendentes.
3. Confira a lista. Marque **Confirmo que a função atual da tecla 15...**. A tecla 15 de cada perfil não-menus será substituída; não é uma mudança cosmética.
4. Clique em **Sincronizar menu e tecla 15**. A operação grava os YAML e PNG pessoais, com backup automático antes de qualquer alteração.
5. Clique em **Recarregar catálogo (IPC)** para o serviço reconhecer as alterações.
6. Clique em **Abrir menu nos LCDs (IPC)** ou pressione a tecla 15 do equipamento.
7. Para restaurar a função antiga das teclas 15, clique em **Restaurar último backup…**, confirme e, ao concluir, clique em **Recarregar catálogo (IPC)**. Caso algum arquivo tenha sido editado desde a instalação, a restauração será bloqueada.

Se você instalar outro perfil posteriormente, refaça **Inspecionar → Sincronizar → Recarregar** para incorporá-lo ao menu. O processo de sincronização é explícito, não automático.

## Segurança

- Só o clique em **Sincronizar** modifica perfis; só os botões identificados como **IPC** solicitam alteração do serviço/displays.
- `--expected-revision` compara a revisão SHA-256 dos YAML atuais com a inspeção anterior. Qualquer mudança no catálogo exige nova inspeção antes de sincronizar.
- Não é permitida sincronização/restauração se houver edição não salva de uma tecla no Studio.
- Até 14 perfis são exibidos por página. Havendo mais, a tecla 15 do menu controla a paginação; em perfis regulares ela retorna à página inicial.
- A ação da tecla 15 anterior é **substituída**, mas tem backup. Não apaga ações das teclas 1–14.
- Diretórios pessoais usados pelo gerenciador:

```
~/.config/vision02/profiles/
~/.config/vision02/profile-icons/menu-de-perfis/
~/.local/state/vision02/menu-perfis-backups/
```

- O projeto Git, o serviço `vision02.service`, USB/HID e as credenciais OBS **não são modificados** pela instalação da interface.
- Para voltar à versão anterior do código, utilize o Gerenciador de Atualizações com o backup criado ao instalar o ZIP. Isso não desfaz sincronizações pessoais já feitas — para estas, use **Restaurar último backup** na página Menu de Perfis.

## Testes

Testes de integração estão em `tests/test_studio_profile_menu_v15.py`. Exercitam detecção dos nomes, substituição somente da tecla 15, paginação, bloqueio por revisão alterada, ícones PNG, idempotência e restauração protegida.

Execute a suíte completa no Ubuntu pelo Gerenciador de Atualizações ou pelo projeto:

```bash
.venv/bin/python -m pytest -q
```

Resultado esperado partindo da v14.2: **1.554 testes aprovados** (1.535 existentes + 19 novos).
