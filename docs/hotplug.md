# Recuperação automática USB da Vision 02

O processo `vision02.hotplug` supervisiona `vision02 profile run`. É executado pelo
`systemd --user` enquanto a sessão gráfica estiver ativa.

## Comportamento

- Sem Vision 02 detectada: o supervisor permanece ativo, aguardando sem abrir USB.
- Ao detectar VID:PID `0a00:1000` no `hidraw`: inicia a CLI existente, que
  inicializa os 15 displays e carrega o perfil Desenvolvimento.
- Ao desconectar ou transferir o USB para a VM: interrompe a CLI com `SIGINT`,
  aguarda o encerramento e volta a esperar o dispositivo.
- Ao reconectar: cria novo processo, nova sessão HID e recarrega os displays.
- Se a CLI encerrar inesperadamente com o USB presente: tenta novamente com
  espera progressiva limitada a 60 segundos para evitar loops.
- Ao encerrar o serviço: encerra a CLI de forma ordenada e depois sai.

A detecção utiliza **sondagem leve de sysfs** a cada segundo (não `udev`). Não
há `sudo`, acesso a `/dev/uinput` nem modificações no protocolo de 512 bytes.

Após uma reconexão o perfil inicial volta a ser **Desenvolvimento**. O último
perfil ativo não é persistido nesta versão. Os atalhos GNOME Wayland podem
precisar de nova autorização quando uma nova sessão D-Bus for aberta.

## Administração

```bash
systemctl --user status vision02.service
journalctl --user -u vision02.service -f
systemctl --user restart vision02.service
systemctl --user stop vision02.service
```

Quando o periférico estiver desconectado, o serviço continua `active (running)`;
os logs mostram `Aguardando Vision 02 via hidraw...`. Isso é esperado.

## Validação manual de hotplug

1. Confira `systemctl --user is-active vision02.service` (`active`).
2. Em repouso, desconecte a Vision 02 da porta USB, sem estar trocando perfis.
3. Veja no `journalctl` que o supervisor interrompeu o controlador e passou a
   aguardar. O `systemd` deve permanecer ativo.
4. Reconecte. O perfil Desenvolvimento deve reaparecer automaticamente.
5. Pressione a tecla 15 para alternar para Observabilidade e novamente para
   Desenvolvimento. Confira os demais botões.
6. Repita o teste transferindo o USB para o VirtualBox somente se necessário.

**Não inicie `vision02 listen` ou `vision02 profile run` manualmente enquanto
`vision02.service` estiver ativo.** Pare o serviço antes de depurar o hardware:

```bash
systemctl --user stop vision02.service
# ... testes com o hardware ...
systemctl --user start vision02.service
```

## Recuperação

O instalador salva a unidade systemd anterior em:
`~/.cache/vision02-hotplug-backups/<timestamp>/vision02.service`.
Para retornar à configuração anterior, pare o serviço, copie o backup sobre
`~/.config/systemd/user/vision02.service`, rode `systemctl --user daemon-reload`
e depois `systemctl --user restart vision02.service`.
