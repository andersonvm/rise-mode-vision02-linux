# Composição LCD — etapa 2

Evolução da interface de composição, sem modificar o protocolo USB/HID ou o esquema YAML.
A versão utiliza os mesmos campos `appearance.image_x`, `image_y`, `image_scale`,
`offset_x` e `offset_y` da composição anterior.

## No Studio

1. Abra **Teclas**, escolha perfil e tecla e expanda **Composição**.
2. No modo **Imagem**, arraste a alça azul do canto inferior direito para alterar o tamanho (25%–200%). Arrastar fora da alça move a imagem.
3. No modo **Texto**, arraste para ajustar o deslocamento, limitado a ±40 px.
4. As linhas azuis indicam o centro; linhas amarelas indicam alinhamentos inteligentes, próximos ao centro ou às bordas. A opção de grade fixa permanece disponível.
5. Use **Zoom da edição** (100%, 150% e 200%) apenas para inspecionar detalhes. O zoom *não altera o tamanho do LCD nem os valores gravados*; a imagem da prévia é recortada visualmente na janela.
6. **Desfazer** e **Refazer** recuperam operações de arrasto/redimensionamento/restauração; `Ctrl+Z` / `Ctrl+Shift+Z` funcionam quando o foco não está em campos de texto.
7. **Restaurar posição/tamanho do elemento** redefine apenas o elemento selecionado: imagem = X/Y 0 e escala 100%; texto = deslocamentos X/Y 0.
8. **Salvar YAML com backup** e **Aplicar ao dispositivo (IPC)** continuam sendo passos separados.

## Segurança e compatibilidade

- O histórico é local à tecla em edição e é reiniciado ao carregar outra tecla.
- O histórico possui no máximo 64 entradas; novas edições após um **Desfazer** descartam a sequência de **Refazer**.
- As operações não escrevem YAML até o salvamento explícito e não executam ações de teclas.
- A prévia continua sendo produzida pelo renderizador do dispositivo, sem segunda conexão HID.
- Os perfis antigos continuam válidos e mantêm valores padrão quando não possuem campos de composição.
- A alça usa os limites da imagem renderizada; seu desenho é apenas uma aproximação quando a imagem de origem contém margens transparentes. Para tamanhos que extrapolem a prévia, a alça permanece acessível na borda do editor.
