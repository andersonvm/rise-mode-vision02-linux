# Aparência visual integrada ao Vision 02 Studio

A seção **Teclas → Aparência visual** utiliza os mesmos campos de `KeyAppearance`
que o renderizador e o editor avançado já conhecem. Não há mudança de formato
YAML ou de protocolo USB.

1. Escolha o perfil e a tecla física.
2. Expanda **Aparência visual — fontes, cores e posição**.
3. Ative **Usar aparência personalizada** (o modo desligado conserva a renderização legada).
4. Ajuste fontes Sans/Serif/Mono, normal/negrito, tamanho 8–36, cores #RRGGBB,
   alinhamento, posição X/Y do texto (−40 a 40), exibir texto e ajuste de imagem.
5. Aguarde a prévia local, ou use **Pré-visualizar (local)**. Nenhuma prévia executa ações.
6. Use **Salvar YAML com backup** e depois **Aplicar ao dispositivo (IPC)**.

O renderizador existente suporta **preencher**, **conter** e **esticar** uma imagem.
Os deslocamentos X/Y afetam **somente o texto**, não o ícone. Escala numérica ou
arraste de imagem exigem mudança de modelo, não fazem parte desta entrega.

O salvamento valida o perfil em um YAML temporário, cria backup e impede salvar
sobre alterações concorrentes. Perfis pessoais existentes não são modificados
pela instalação; apenas pela ação explícita de **Salvar YAML**.
