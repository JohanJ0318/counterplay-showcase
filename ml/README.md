# Seeing positions: a PyTorch win-probability model for CS2 rounds

Counterplay's decision scorer estimates, at every moment of a round, the
chance the CT side wins it. The shipped model (`counterplay/model.py`) is
gradient-boosted trees on eleven numbers: players alive, equipment, time
left, the bomb, map, buy type. It never sees a position, so it cannot tell
a stacked bombsite from a spread one.

This folder asks whether seeing where all ten players stand improves that,
and whether 104 professional maps help a model meant for college teams.

## What is here

| file | what it does |
|---|---|
| `data.py` | Attaches a snapshot of all ten players (position, health, facing, bombsite) to every moment the shipped model is scored on. Alive or dead comes from the death events, positions from 8 Hz samples. |
| `model.py` | `WinNet`: a per-player encoder conditioned on the map, one self-attention layer across all ten players, mean and max pooling per side (so player order never matters), and a small head. About 27,000 parameters. |
| `train.py` | The training loop: AdamW, gradient clipping, early stopping on held-out matches, and pro-then-college fine-tuning. |
| `evaluate.py` | Every arm scored on the same splits, the same isotonic calibration and the same calibration gate as the shipped model. |

```bash
pip install -r requirements.txt
pip install -r requirements-ml.txt --extra-index-url https://download.pytorch.org/whl/cpu
python -m ml.data                       # build the snapshot cache
python -m ml.evaluate                   # every arm, 20 seeds
python -m ml.evaluate NET NETPRO --seeds 5
```

## How it is measured

* **Splits are by match, never by row.** The moments inside one round are
  near copies of each other; a row split leaks the answer.
* **Two held-out protocols, 20 seeds each.** DIV trains on the 138 NECC
  placement maps and tests on 26 division maps played later. RAND tests on
  26 random college maps and trains on the other 138.
* **Calibration, not just accuracy.** A coach reads "your chance fell from
  60% to 25%", so 30% has to mean 30%. Every arm gets the same isotonic
  layer, fitted on matches it never trained on, and is judged on expected
  calibration error divided by the error a perfectly calibrated model would
  show on the same predictions (a parametric bootstrap). Under 2.5x passes.
* **Test maps are always college maps.** Pro maps only ever train.

## Results (2026-10-14, 20 seeds, medians)

| arm | what it is | DIV AUC | DIV log loss | RAND AUC | RAND log loss | RAND passes |
|---|---|---|---|---|---|---|
| LGB | shipped LightGBM | 0.869 | 0.448 | 0.870 | 0.453 | 14/20 |
| SMALL | LightGBM cut down to 7 leaves | 0.898 | 0.398 | 0.892 | 0.414 | 15/20 |
| MLP | network, no positions | 0.896 | 0.404 | 0.889 | 0.419 | 15/20 |
| SMALLPOS | SMALL + hand-made position summaries | **0.907** | **0.381** | **0.898** | **0.402** | 15/20 |
| NET | network with all ten players | 0.905 | 0.384 | 0.891 | 0.415 | 13/20 |
| NETPRO | NET pretrained with 104 pro maps | **0.907** | **0.381** | 0.896 | 0.410 | 15/20 |

(LGB from `tools/baselines.py`, same protocols and seeds.)

What it says:

1. **The shipped model was too big, not too small.** Cutting LightGBM down
   gained 0.02 to 0.03 AUC. About 47,000 rows sounds like a lot; it is
   about 4,000 college rounds whose moments repeat each other.
2. **Positions carry real signal.** Both ways of adding them beat SMALL on
   both protocols, mostly through total health per side and players in
   each bombsite.
3. **The network matches the trees only with pro pretraining.** Trained on
   college maps alone it ties SMALL on RAND. Pretrained on pro maps and
   fine-tuned on college it reaches SMALLPOS on DIV and comes close on RAND.
   Pro data helps the network and barely moves the trees, which is the
   pattern of a model limited by data rather than by design.
4. **No model fixes the calibration tail.** Every arm has a RAND split near
   4x the gate. That is which 26 maps land in the test set, not the model.

So, today, the honest pick for the product is SMALLPOS: cheaper, as good,
and easy to explain. The network is the one with room to grow, and what it
needs is more matches, pro and ESEA, not more layers.

## Things that went wrong on the way, and what they taught

* **Reading positions a moment late.** The first snapshots disagreed with
  the event counts on 1.6% of rows, and it looked like the 8 Hz sample
  rate. It was not: 83% of them had the next death within a quarter of a
  second, and the snapshot was read one sample after the event, catching
  the second kill of a trade. A faster sample rate would not have fixed
  it, since a double kill can share a tick. Alive state now comes from the
  death events, which record who died and when; agreement went to 99.2%.
* **The last 0.8% exposed a bug in the shipped model.** Every remaining
  mismatch is a side with fewer than five players (a disconnect). The
  positions are right and the event model, which assumes 5 on 5, is not.
* **Retrieval by meaning alone** (the coach's read resource library,
  `tools/resources.py`) pulled Nuke CT guides for Nuke T. Filtering on tags
  first and ranking by embedding second fixed it.
