# Changelog

All released versions are archived on Zenodo. Earlier versions remain citable but report different scores.

## 4.0.0 — 2026-08-10

DOI: [10.5281/zenodo.21878587](https://doi.org/10.5281/zenodo.21878587). This version corresponds to the results reported in the accompanying paper.

- Regenerated the GS and GSC `rdfs3_7` datasets and task files. The first premise had been generated with `rdfs:domain` where the pattern requires `rdfs:range`; the affected evaluation cells were re-run.
- Scoring now excludes premise triples from the reference side as well as from the model output. The scored reference is `expected_output \ premise_knowledge`. This mainly affects GSC, where case conversion can map distinct source terms onto the same surface form.
- Flex-mode scoring now treats repeated identical output triples as a set, consistent with RDF graph semantics, and requires terms to be separated by a comma or whitespace.
- Evaluation results and reports were recomputed accordingly.
- Added counterfactuality validation of the perturbed variants (LS, RVA, GS, GSC) against DBpedia and Wikidata (`data/validation/`).

## 3.1.0 — 2026-05-10

DOI: [10.5281/zenodo.20095646](https://doi.org/10.5281/zenodo.20095646). Earliest publicly available version; versions prior to 3.1.0 have been withdrawn from Zenodo.

Scores reported by this version predate the scoring and dataset fixes listed under 4.0.0.
