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

So the pick for the product was SMALLPOS: cheaper, as good, and easy to
explain. The network is the one with room to grow, and what it needs is
more matches, not more layers.

### Adding 115 ESEA League maps (2026-10-14)

Season 58 North America, Main, Intermediate and Open (`tools/esea.py`),
tier `esea`, never tested on. Same protocols and seeds as above.

| arm | DIV AUC | DIV log loss | DIV passes | RAND AUC | RAND log loss | RAND passes |
|---|---|---|---|---|---|---|
| SMALLPOS | 0.9071 | 0.3809 | 19/20 | 0.8976 | 0.4023 | 15/20 |
| SMALLPOS + ESEA rows | 0.9082 | 0.3778 | **20/20** | **0.8995** | **0.3991** | 15/20 |
| NET | 0.9054 | 0.3822 | 20/20 | 0.8922 | 0.4125 | 14/20 |
| NETPRO | 0.9079 | 0.3805 | 19/20 | 0.8953 | 0.4070 | 16/20 |
| NETESEA | **0.9096** | **0.3761** | 19/20 | 0.8948 | 0.4064 | 14/20 |
| NETBOTH (pro + ESEA) | 0.9084 | 0.3776 | 19/20 | 0.8944 | 0.4080 | 16/20 |

* ESEA helped every arm on both protocols: the first data source that
  moved the trees as well as the network.
* ESEA pretraining beat pro pretraining with about the same number of
  maps, and mixing the two was no better than ESEA alone: the population
  matters more than the volume.
* The network now wins DIV and still trails the trees on RAND by about
  0.005 AUC. It gains more per map than the trees do.
* Calibration tails are unchanged.

New pick: SMALLPOS trained with the ESEA rows.

### 232 ESEA maps, and the scorer switched (2026-10-14)

Double the ESEA set, same seeds. SWEEP is tools/seedsweep.py's split.

| arm | DIV AUC / log loss / passes | RAND AUC / log loss / passes | SWEEP AUC / log loss / passes / median |
|---|---|---|---|
| SMALLPOS | 0.9071 / 0.3809 / 19 | 0.8976 / 0.4023 / 15 | 0.8919 / 0.4095 / 14 / 2.01 |
| SMALLPOS + 232 ESEA | **0.9097 / 0.3758 / 20** | **0.8998 / 0.3974** / 15 | **0.8958 / 0.4023 / 15** / 2.18 |
| NETESEA (232) | 0.9085 / 0.3765 / 19 | 0.8971 / 0.4075 / 15 | 0.8936 / 0.4069 / 12 / 2.17 |

The trees gained again on every protocol; the network gained on RAND and
lost a little on DIV, and is now within 0.003 AUC of the trees on RAND.

SMALLPOS + ESEA is now the scorer's model (counterplay/model.py, config
"smallpos"). Run through the scorer's own code, tools/seedsweep.py gives
15 of 20, median 2.18, AUC 0.8958: the evaluation above, to the digit.
Against the model it replaced (12 of 20, median 2.36, AUC 0.8588) it is
better on every number and passes the holdout rule (DIV 20 of 20 against
18 fixed in advance). The sweep still fails a quarter of splits, so a
coach is still not shown a number from it.

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

### 332 ESEA maps: both models have levelled off (2026-10-14)

| ESEA maps | NETESEA RAND AUC | SMALLPOS+ESEA RAND AUC | gap |
|---|---|---|---|
| 0 | 0.8922 | 0.8976 | 0.0054 |
| 115 | 0.8948 | 0.8995 | 0.0047 |
| 232 | 0.8971 | 0.8998 | 0.0027 |
| 332 | 0.8961 | 0.9000 | 0.0039 |

DIV at 332: trees 0.9098 (20 of 20), network 0.9084 (17 of 20), both flat
against 232. The last hundred maps moved neither model beyond noise, so
more ESEA is not the lever any more. What is left for the network: more
COLLEGE maps (it always finishes on the same 164), and how it uses ESEA
(longer pretraining, or some ESEA kept in the college stage).

### Skill levels, matched pretraining, longer pretraining, movement (2026-10-14)

NC State Red's captain: NECC's divisions are far apart in skill, and some
ESEA divisions sit close to some NECC ones. `ml/levels.py` gives every
college and ESEA round each side's level (NECC D1-D4 from the team's
division, ESEA Open/Intermediate/Main, pro).

Which ESEA division plays most like each NECC division: train the small
LightGBM on one source alone and see how well it predicts each division
(log loss, lower is closer):

| trained on | D1 | D2 | D3 | D4 |
|---|---|---|---|---|
| ESEA Open | **0.3715** | 0.4067 | **0.4171** | **0.3922** |
| ESEA Intermediate | 0.3779 | **0.3972** | 0.4197 | 0.4041 |
| ESEA Main | 0.3790 | 0.4086 | 0.4203 | 0.4008 |
| pro | 0.3747 | 0.4133 | 0.4344 | 0.4124 |

Open is closest to D1, D3 and D4, Intermediate to D2; Main never is; pro
is furthest from D3 and D4. Small samples (340 to 750 rounds a division).

Then each idea against the same model without it (332 ESEA maps, 20 seeds):

| arm | RAND AUC / log loss / passes | DIV AUC / log loss / passes |
|---|---|---|
| SMALLPOS+ESEA (the scorer) | 0.9000 / 0.3987 / 16 | 0.9098 / 0.3748 / 20 |
| + each side's level | 0.9010 / 0.3977 / 15 | 0.9091 / 0.3769 / 19 |
| NETESEA | 0.8961 / 0.4047 / 15 | 0.9084 / 0.3781 / 17 |
| + each side's level | 0.8973 / 0.4014 / 17 | 0.9080 / 0.3809 / 16 |
| pretrained on Open + Intermediate only | 0.8946 / 0.4065 / 15 | 0.9076 / 0.3785 / 20 |
| **longer pretraining, ESEA kept in fine-tuning** | **0.8985 / 0.4018** / 15 | 0.9082 / **0.3771** / **20** |
| + movement, weapon, grenades per player | 0.8950 / 0.4042 / 15 | 0.9066 / 0.3811 / 20 |

* Levels: no clear gain for either model. The divisions differ, but the
  models already see what makes them differ (economy, positions, fights).
* Matched ESEA: worse. At this size, more data beats better-matched data.
* Longer pretraining (NETLONG: patience 10, up to 80 epochs, half as many
  ESEA rows as college rows kept in the college stage): better on both
  protocols, and the network's best so far, 0.0015 AUC behind the trees on
  RAND. The way to train the network from here.
* Movement and weapons per player: no gain, slightly worse. The moments
  scored are kills and plants, where most players stand in or react to a
  fight; movement may matter more between events. Off by default
  (WinNet use_kit); NETKIT reruns it.

## 2026-10-23: with NECC weeks 3-4 (313 college maps)

NEW is the fair test: train on every college map parsed before 2026-10-23,
test on the 148 weeks 3-4 maps no model had seen. ECE is printed beside the
floor ratio because the ratio grows with test size (NEW's test is 26,299
rows), so "passed" is not comparable across protocols; ECE is.

| arm | NEW AUC | NEW ECE | RAND AUC | RAND ECE |
|---|---|---|---|---|
| SMALLPOS+ESEA (shipped scorer) | 0.8960 | 0.0156 | 0.8997 | 0.0154 |
| SMALLPOS+ESEA+LVL | 0.8960 | 0.0151 | 0.8998 | 0.0157 |
| NETESEA | 0.8938 | 0.0147 | 0.8973 | 0.0150 |
| NETLONG | 0.8934 | 0.0143 | 0.8970 | 0.0163 |
| NETMATCH | 0.8928 | 0.0151 | 0.8958 | 0.0163 |
| NETKIT | 0.8913 | 0.0147 | 0.8964 | 0.0170 |
| NET | 0.8879 | 0.0164 | 0.8942 | 0.0185 |
| MLP | 0.8874 | 0.0136 | 0.8899 | 0.0163 |
| LGB (old shipped trees) | 0.8686 | 0.0187 | 0.8830 | 0.0186 |

Trees 20 seeds, networks 10. The trees still rank best on both tests (by
0.002 to 0.003 AUC). The networks' small ECE edge on NEW does not hold on
RAND, so it is not a real difference. The scorer stays SMALLPOS+ESEA.
NETKIT had never actually run with its kit: train() dropped `use_kit`
until this date; with it, it is no better than NETESEA.

## 2026-10-23: lessons, callouts and vision, and a blend (ml/extras.py)

Same 10 seeds for every arm. LESSONS: the network also learns which side
loses the next player, which slot dies next and whether the bomb goes down
within 10 s (AUX_WEIGHT 0.3 each). VIEW: each player's callout as a
(map, callout) embedding, and what the enemy can see of them (seen now,
sees now, seconds since last seen; the game's spotting fires on 1.7% of
samples, "seen within 10 s" on 20% of living players). ENS averages the
trees and a network before calibration.

| arm | NEW AUC | NEW logloss | NEW ECE | RAND AUC | RAND logloss | RAND ECE |
|---|---|---|---|---|---|---|
| SMALLPOS+ESEA (shipped) | 0.8958 | 0.4047 | 0.0134 | 0.8979 | 0.3946 | 0.0143 |
| NETESEA | 0.8938 | 0.4111 | 0.0147 | 0.8973 | 0.3986 | 0.0150 |
| NETVIEW | 0.8919 | 0.4122 | 0.0137 | 0.8959 | 0.4012 | 0.0164 |
| NETLESSONS | 0.8952 | 0.4060 | 0.0155 | 0.8978 | 0.3958 | 0.0154 |
| NETPLUS | 0.8946 | 0.4068 | 0.0166 | 0.8974 | 0.3962 | 0.0173 |
| ENS (trees + NETESEA) | 0.8965 | 0.4047 | 0.0149 | 0.8995 | 0.3934 | 0.0158 |
| ENSPLUS (trees + NETPLUS) | 0.8974 | 0.4022 | 0.0133 | 0.9002 | 0.3917 | 0.0158 |

Lessons are the lever: they close the network's gap to the trees on ranking
(0.0006 and 0.0001 behind) and most of it on log loss. Callouts and vision
cost a little on both tests (too many embedding ids for the rounds there
are; the spotting signal is thin). The blend is the only arm ahead of the
trees on both tests, on AUC and log loss; calibration is level on NEW and
0.0015 worse on RAND. Next to test: trees + NETLESSONS, without the view.

## 2026-10-23: improving NETLESSONS (more moments, lessons, copies, regions)

Screen 1 (5 seeds) added each change on top of NETLESSONS together with
TIMED moments (a state every 2 s between events, training only; 550,287
rows). The timed moments cost ranking on both tests (NEW 0.8937 -> 0.8899,
RAND 0.9005 -> 0.8982): near-copies of one another, so the network learns
rounds rather than the game. Longer pretraining added nothing. Screen 2
(10 seeds, event rows only; net seeds are seed*100+copy, so not the same
draws as the tables above):

| arm | NEW AUC | NEW logloss | NEW ECE | RAND AUC | RAND logloss | RAND ECE |
|---|---|---|---|---|---|---|
| NETLESSONS | 0.8940 | 0.4077 | 0.0160 | 0.8990 | 0.3960 | 0.0157 |
| NETM (+ next killer, time to next death, how the round ends) | 0.8952 | 0.4043 | 0.0159 | 0.9001 | 0.3926 | 0.0173 |
| NETMW (lessons weighted 0.6) | 0.8953 | 0.4051 | 0.0150 | 0.8995 | 0.3941 | 0.0188 |
| NETMREG (+ regions every map shares) | 0.8950 | 0.4069 | 0.0133 | 0.8987 | 0.3952 | 0.0159 |
| NETLESSONSx5 (five copies averaged) | 0.8960 | 0.4037 | 0.0145 | 0.9007 | 0.3909 | 0.0175 |
| **NETMx5 (more lessons, five copies)** | **0.8969** | **0.4020** | 0.0148 | **0.9009** | **0.3911** | 0.0165 |
| SMALLPOS+ESEA (shipped trees, earlier table) | 0.8958 | 0.4047 | 0.0134 | 0.8979 | 0.3946 | 0.0143 |
| ENSLESSONS (trees + NETLESSONS) | 0.8973 | 0.4017 | 0.0146 | 0.8999 | 0.3913 | 0.0158 |

NETMx5 is the first network alone ahead of the trees on both tests, on
ranking and log loss; it matches the trees+network blend. The trees still
have the lower ECE (0.0014 and 0.0022). Not shipped.

## 2026-10-23: NETMx5 against the trees, 20 seeds, three tests

| proto | arm | passed | ratio med | ECE | AUC | logloss |
|---|---|---|---|---|---|---|
| NEW | SMALLPOS+ESEA | 4/20 | 3.28 | 0.0156 | 0.8960 | 0.4045 |
| NEW | NETMx5 | 2/20 | 3.40 | 0.0169 | 0.8969 | 0.4029 |
| RAND | SMALLPOS+ESEA | 17/20 | 1.32 | 0.0154 | 0.8997 | 0.3940 |
| RAND | NETMx5 | 18/20 | 1.36 | 0.0161 | 0.9009 | 0.3914 |
| DIV | SMALLPOS+ESEA | 19/20 | 1.43 | 0.0170 | 0.9097 | 0.3751 |
| DIV | NETMx5 | 19/20 | 1.79 | 0.0215 | 0.9105 | 0.3746 |

The 10-seed lead holds on ranking and log loss on all three tests, and it
is small (AUC +0.0008 to +0.0012, log loss -0.0005 to -0.0026). The trees
are better calibrated on all three, by the most on DIV (0.0170 vs 0.0215).
The network takes about 300 times as long to train. Not shipped.
