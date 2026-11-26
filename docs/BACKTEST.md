# Backtest das regras de geada e chuva (2026-11-26)

Previsão feita **1 dia antes** (Open-Meteo Previous Runs API) contra a **reanálise ERA5** (Open-Meteo Historical Weather API), por hora, no horário de Brasília.

**Leia isto antes do número:** a verdade aqui é uma reanálise em grade, **não uma estação do INMET na lavoura**. A reanálise suaviza as mínimas e costuma não registrar geada local; então o recorte mostra o comportamento da regra, não uma promessa de acerto ao produtor. Uso gratuito do Open-Meteo é só não comercial.

Períodos: 2024-05-01 a 2024-09-30, 2025-05-01 a 2025-09-30. Evento de geada: mínima da madrugada (0h-9h) <= 3 °C.

## Geada por ponto (alertando quando a previsão <= limite)

| Ponto | Noites | Geadas reais | Acertos | Alarmes falsos | Perdas | Precisão | Recall | Erro médio (°C) | Viés (°C) |
|---|---|---|---|---|---|---|---|---|---|
| Passo Fundo (RS) | 306 | 15 | 10 | 5 | 5 | 67% | 67% | 1.05 | +0.39 |
| Vacaria (RS) | 306 | 24 | 21 | 3 | 3 | 88% | 88% | 0.92 | +0.37 |
| Lages (SC) | 306 | 30 | 24 | 4 | 6 | 86% | 80% | 1.01 | +0.16 |
| Guarapuava (PR) | 306 | 13 | 11 | 21 | 2 | 34% | 85% | 2.44 | -2.28 |
| Sorriso (MT), controle | 306 | 0 | 0 | 0 | 0 | - | - | 1.18 | -0.42 |
| **Total** | 1530 | 82 | 66 | 33 | 16 | 67% | 80% | | |

## Quanto de margem no limite? (previsão <= limite + margem)

| Margem | Acertos | Alarmes falsos | Perdas | Precisão | Recall |
|---|---|---|---|---|---|
| +0 °C | 66 | 33 | 16 | 67% | 80% |
| +1 °C | 77 | 59 | 5 | 57% | 94% |
| +2 °C | 81 | 103 | 1 | 44% | 99% |

## Chuva forte (dia com 5 mm ou mais)

Dias avaliados: 1530 · eventos reais: 282 · acertos: 213 · alarmes falsos: 30 · perdas: 69 · precisão 88% · recall 76%.

A chuva em grade é ainda mais incerta que a temperatura (chuva local de verão em pancadas quase nunca aparece igual na previsão e na reanálise).

## O que este recorte mostra (e o que não mostra)

- **Funciona onde há geada de verdade.** Em 3 dos 4 pontos do Sul a previsão de 1 dia antes pegou 67% a 88% das geadas (recall de 67%, 88% e 80%), com erro médio de cerca de 1 °C. No ponto de controle quente (Sorriso) não houve nenhuma geada e a regra não teria disparado nenhuma vez, como se espera.
- **Há um ponto fraco evidente: Guarapuava.** Muitos alarmes falsos (21) e viés de -2,3 °C: a previsão sai mais fria que a reanálise. **Hipótese não verificada:** diferença entre a altitude da célula da previsão e a do local (Guarapuava fica em torno de 1.100 m). Se for isso, usar a altitude do nosso modelo de relevo para corrigir a temperatura ajudaria. Vale testar com **estações reais** (INMET) antes de mexer na regra.
- **A margem de +1 °C troca alarme falso por menos perdas:** o recall sobe de 80% para 94% e a precisão cai de 67% para 57%. Perder uma geada custa mais que um aviso a mais, mas o limite diário e o silêncio existem justamente para não encher o produtor; a decisão do valor é do agrônomo.
- **Chuva forte (5 mm no dia):** 76% de recall e 88% de precisão nesta amostra.
- **Não mostra:** acerto contra estação na lavoura; o efeito do ajuste de relevo por baixada (precisa de medições locais de temperatura); nem o desempenho em outras épocas e regiões. Backtest de colheita e de pulverização não foi feito (não há "verdade" pública para a janela de pulverização).
- Reproduzir: python -m app.cli backtest docs/BACKTEST.md (precisa de internet; as contagens podem variar um pouco porque o arquivo de previsões passadas é atualizado).
