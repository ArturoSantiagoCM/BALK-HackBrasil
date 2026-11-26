# Bibliotecas do navegador copiadas para este repositório (`web/vendor/`)

Servidas pelo próprio BALK (sem CDN: nada de terceiros é carregado pelo navegador, exceto as imagens do mapa, ver `docs/OPERACAO.md`).
Todas as licenças abaixo são permissivas e compatíveis com a licença do BALK (MIT). O aviso de cada uma acompanha a redistribuição, como elas exigem.

| Arquivos | Biblioteca | Versão | Licença |
|---|---|---|---|
| `maplibre-gl.mjs`, `maplibre-gl-worker.mjs`, `maplibre-gl.css` | [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) | 6.19.0 | BSD-3-Clause. Texto completo, com os avisos do código herdado do Mapbox GL JS 1.x, glfx.js e d3-color, em [`LICENSE-maplibre-gl.txt`](LICENSE-maplibre-gl.txt) |
| `terra-draw.umd.js`, `terra-draw-maplibre-gl-adapter.umd.js` | [Terra Draw](https://github.com/JamesLMilner/terra-draw) e o adaptador para MapLibre | pacotes npm `terra-draw` e `terra-draw-maplibre-gl-adapter` (os arquivos não trazem a versão: conferir com `npm view`) | MIT, texto abaixo |
| `turf.min.js` | [Turf.js](https://github.com/Turfjs/turf) | pacote npm `@turf/turf` (o arquivo não traz a versão: conferir com `npm view`) | MIT, texto abaixo |

## Terra Draw (e `terra-draw-maplibre-gl-adapter`)

```
Copyright 2022 James Milner

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Turf.js

```
The MIT License (MIT)

Copyright (c) 2019 Morgan Herlocker

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

Textos copiados dos arquivos `LICENSE` dos repositórios oficiais em 26/11/2026.

Por que 6.19.0 do MapLibre: as versões 5.x tinham um aviso de segurança crítico publicado no npm.
Para atualizar: baixe o pacote novo do npm, copie os arquivos de `dist/`, atualize os textos acima, rode `tests/test_site.py` e abra `/app/mapa.html` (desenhar, salvar e editar um talhão).
