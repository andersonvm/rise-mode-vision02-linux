# Vision02 Studio v1.0.0 — primeira versão estável

Esta é a **linha de base funcional** do projeto Rise Mode Vision 02 Linux.
A numeração pública recomeça em **v1.0.0**. Protótipos e versões
experimentais anteriores permanecem no histórico, sem serem apagados.

## Recursos incluídos

- Comunicação USB/HID com as 15 teclas e os 15 LCDs 100 × 100.
- Inicialização dos displays em lote (`CLE FF`, JPEGs, `STP` único),
  eliminando as bordas brancas inclusive após ligar o Ubuntu a frio.
- Controle de brilho global de 0% a 100% (`LIG`), via CLI e Studio,
  com persistência da preferência e restauração após reconexão.
- Serviço com supervisor hotplug, IPC Unix local e recuperação USB.
- Vision02 Studio GTK4/libadwaita com editor visual, composição,
  galeria de ícones, presets e preview dos displays.
- Perfis YAML, catálogo, Menu de Perfis na tecla 15 e ações programáveis.
- Integração OBS Studio, dashboards e indicadores locais.

## Validação de referência

- 1.600 testes automatizados aprovados na árvore de desenvolvimento em
  21/10/2026, antes da alteração de metadados de versão.
- Brilho e persistência validados no dispositivo físico.
- Correção das bordas brancas validada após desligamento completo.
- O pacote Debian não ativa nem altera automaticamente o serviço HID.

## Instalação

Baixe `vision02-studio-desktop_1.0.0-1_all.deb` e `SHA256SUMS` da release.
Confira o checksum e instale o pacote com o APT. Se já estiver instalado
um RC experimental com numeração superior (por exemplo `16.0.0~rc1-1`),
o APT identificará a v1.0.0 como downgrade de versão; revise a operação
antes de confirmar. Perfis em `~/.config/vision02` não são sobrescritos.

## Histórico

A release `v15.0.0` permanece publicada apenas como histórico da etapa
experimental. **v1.0.0** é o início da numeração estável deste projeto.
