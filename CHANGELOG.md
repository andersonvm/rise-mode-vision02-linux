# Changelog

## [1.0.0] - 2026-10-21

Primeira versão estável pública. A numeração foi reiniciada após a fase
experimental; versões e commits anteriores continuam no histórico.

### Incluído e validado

- Vision02 Studio GTK4/libadwaita: edição visual, perfis, ícones e presets.
- 15 teclas com LCD, perfis YAML, Menu de Perfis e ações programáveis.
- Inicialização USB/HID em lote sem bordas brancas após inicialização a frio.
- Brilho global 0–100% pelo Studio e terminal, com persistência e hotplug.
- Integração com OBS Studio, previews e dashboards locais.
- 1.600 testes automatizados aprovados na árvore de trabalho antes do
  ajuste de versões (testes de release devem ser executados novamente).

### Distribuição

- Pacote Debian autônomo `vision02-studio-desktop_1.0.0-1_all.deb`.
- Publicação por tag `v1.0.0`; builds de `main` não publicam releases.
- Não modifica perfis pessoais nem configura automaticamente o serviço HID.

## [0.2.0] - 2026-10-13

### Adicionado

- Gerenciamento de sessão HID persistente.
- Controle de operações concorrentes de leitura e escrita.
- Sincronização do ciclo de vida da conexão.
- Reconexão explícita da controladora.
- Estado de falha da sessão HID.
- Cache seletivo de imagens por display usando SHA-256.
- Parâmetro `skip_unchanged` em `Vision02.set_image()`.
- Testes automatizados de transporte, concorrência e cache.

### Melhorado

- Segurança durante abertura e fechamento do dispositivo.
- Tratamento de falhas USB.
- Serialização das transmissões JPEG.
- Responsividade das teclas durante atualizações dos LCDs.
- Redução de transferências USB redundantes.

### Validado

- Reconhecimento da Rise Mode Vision 02 no Linux.
- Funcionamento das 15 teclas físicas.
- Atualização dos 15 displays LCD.
- Transmissão em sessão HID persistente.
- Recebimento de eventos durante transmissões JPEG.
- Cache seletivo de imagens no hardware.
- 39 testes automatizados aprovados.

### Limitações conhecidas

- Reconexão automática ainda não implementada.
- Ausência de confirmação individual de renderização pelo firmware.
- Estabilidade prolongada ainda não avaliada.
- Gerenciamento de perfis e ações ainda não implementado.

## [0.1.0]

### Adicionado

- Implementação inicial do protocolo proprietário da Vision 02.
- Comunicação Linux usando hidraw.
- Descoberta por VID/PID.
- Inicialização do dispositivo.
- Leitura de eventos das teclas.
- Codificação e transmissão de imagens JPEG.
- Interface de linha de comando.
