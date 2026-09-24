"""Publishing an address-based signature: rounded, assessed, suppressed where needed."""
import numpy as np
import pandas as pd
import pytest

from anonymate import CATALOGUE, Population, QidColumn, Threshold
from anonymate.publicatie import COLUMN, Plan, add_baseline, explore, precision_loss
from anonymate.risk import Status, assess
from anonymate.signature import baseline


def make_population(n=400, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        rows.append(dict(
            vbo_id=f"{i:016d}", postcode6=f"80{i // 20:02d}AB", huisnummer=i % 20 + 1,
            huisletter=None, toevoeging=None, eengezins=True, pand_woningen=1,
            bouwjaar=int(rng.choice([1930, 1965, 1985, 2000, 2012])),
            oppervlakte=float(rng.integers(80, 200)), woningtype="vrijstaand",
            aaneengebouwd=False, opp_buitenmuur=float(rng.integers(120, 260)),
            opp_grond=float(rng.integers(50, 120)), opp_dak_plat=0.0,
            opp_dak_schuin=float(rng.integers(60, 140)), opp_scheidingsmuur=0.0,
            gemeente="Zwolle"))
    df = pd.DataFrame(rows)
    for m in ("mwa", "best"):
        sig = baseline(df, m)
        df[[f"sig_{m}_H", f"sig_{m}_tau", f"sig_{m}_Asol"]] = \
            sig[["sig_H", "sig_tau", "sig_Asol"]].to_numpy()
    df = pd.concat([df, baseline(df)], axis=1)
    return df, Population.from_dataframe(df)


@pytest.fixture(scope="module")
def pop():
    return make_population()


def dataset(pop_df, idx):
    sub = pop_df.iloc[idx]
    return pd.DataFrame({"pc": sub["postcode6"].to_numpy(), "nr": sub["huisnummer"].to_numpy(),
                         "gas__m3": 1000.0})


def test_add_baseline_rounds_and_describes_as_qids(pop):
    df, population = pop
    ds = dataset(df, [0, 1, 2])
    out, qids, never = add_baseline(ds, population, Plan("best", {"H": 50, "C": 5000}),
                                    postcode="pc", huisnummer="nr")
    assert (out[COLUMN["H"]] % 50 == 0).all() and (out[COLUMN["C"]] % 5000 == 0).all()
    exact = df["sig_best_H"].iloc[[0, 1, 2]].to_numpy()
    assert np.all(np.abs(out[COLUMN["H"]].to_numpy() - exact) <= 25)
    assert [(q.spec.key, q.tolerance) for q in qids] == [("warmteverlies_best", 25.0),
                                                         ("thermische_massa", 2500.0)]
    assert never == ["pc", "nr"]


def test_published_baseline_counts_like_the_rainbow_table(pop):
    df, population = pop
    ds = dataset(df, [5])
    plan = Plan("nta8800", {"H": 10})
    out, qids, _ = add_baseline(ds, population, plan, postcode="pc", huisnummer="nr")
    a = assess(out, qids, population, Threshold(0.33))
    v = out[COLUMN["H"]].iloc[0]
    expected = int(((df["sig_H"] >= v - 5) & (df["sig_H"] <= v + 5)).sum())
    assert a.records["k_populatie"].iloc[0] == expected


def test_coarser_rounding_publishes_more(pop):
    df, population = pop
    ds = dataset(df, list(range(0, 400, 10)))
    # k only: at a 10% sampling fraction coarse classes would (rightly) fail on delta
    t = explore(ds, population, "best", {"H": [5, 50, 200]}, Threshold(0.09, delta_max=1.0),
                postcode="pc", huisnummer="nr")
    by_step = t.set_index("stap_H")
    assert by_step.loc[200, "publiceerbaar"] >= by_step.loc[50, "publiceerbaar"] \
        >= by_step.loc[5, "publiceerbaar"]
    assert by_step.loc[5, "precisieverlies_%"] < by_step.loc[200, "precisieverlies_%"]
    assert (t["publiceerbaar"] + t["niet_publiceren"] == len(ds)).all()


def test_precision_loss():
    df = pd.DataFrame({COLUMN["H"]: [100.0, 200.0]})
    assert precision_loss(df, Plan("best", {"H": 10})) == pytest.approx(
        np.mean([10 / 12 ** 0.5 / 100, 10 / 12 ** 0.5 / 200]))


def test_other_qids_combine(pop):
    df, population = pop
    ds = dataset(df, [3, 4])
    ds["bouwjaar"] = df["bouwjaar"].iloc[[3, 4]].to_numpy()
    out, qids, _ = add_baseline(ds, population, Plan("best", {"H": 25}), postcode="pc",
                                huisnummer="nr")
    alone = assess(out, qids, population, Threshold(0.33)).records["k_populatie"]
    both = assess(out, qids + [QidColumn("bouwjaar", CATALOGUE["bouwjaar"])], population,
                  Threshold(0.33)).records["k_populatie"]
    assert (both <= alone).all()


def test_cli_publiceer_requires_norm_first_and_writes_without_address(pop, tmp_path, monkeypatch,
                                                                      capsys):
    from anonymate import cli
    from anonymate.store import Store
    df, population = pop
    monkeypatch.setattr(Store, "population", lambda self: population)
    data = tmp_path / "data.csv"
    dataset(df, list(range(0, 400, 50))).to_csv(data, index=False)
    with pytest.raises(SystemExit, match="privacynorm"):
        cli.main(["signatuur", "publiceer", str(data), "--koppel", "pc,nr"])
    out = tmp_path / "uit"
    assert cli.main(["signatuur", "publiceer", str(data), "--koppel", "pc,nr", "--p", "0.09",
                     "--stap", "H=50", "--stap", "C=5000", "--out", str(out)]) == 0
    pub = pd.read_csv(out / "publiceerbaar.csv")
    assert not {"pc", "nr"} & set(pub.columns)
    assert {COLUMN["H"], COLUMN["C"]} <= set(pub.columns)
    assert cli.main(["signatuur", "publiceer", str(data), "--koppel", "pc,nr", "--p", "0.09",
                     "--verken", "H=25,100"]) == 0
    assert "publiceerbaar" in capsys.readouterr().out
