"""LLM decision points.

CiteFlow makes four LLM calls, each with its prompt YAML kept verbatim alongside the
module that uses it (the prompt text *is* part of the algorithm, so keeping it
byte-identical to the original makes drift detectable — see tests/test_prompts_fidelity.py).

1. query_analyzer     — research question -> structured keywords / search queries /
                        discriminative terms
2. seed_selector      — pick papers worth expanding the citation graph from
3. relevance_selector — mark candidate target papers
4. params_decider     — choose forward-expansion year and citation cut-offs
"""
