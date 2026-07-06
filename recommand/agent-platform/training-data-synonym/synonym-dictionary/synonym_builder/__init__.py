"""synonym_builder — LLM-driven ES Solr synonym dictionary generation.

Reads ``item_profile.jsonl`` (Stage 1/2 output), extracts unique brand and
category values, sends each term individually to the LLM for synonym
generation, merges overlapping groups, and writes ``synonyms_solr.txt`` in
ES Solr multi-way format suitable for the ``synonym_graph`` token filter.

Usage::

    from synonym_builder import build_synonyms

    build_synonyms(
        profile_path="output/stage1/item_profile.jsonl",
        dim_dict_path="output/stage1/dim_dictionary_snapshot.yaml",
        output_dir="output/synonyms",
        llm_client=llm,
        prompt_template_path="configs/prompts/synonym_generation.txt",
    )
"""

from __future__ import annotations

from .builder import build_synonyms

__all__ = ["build_synonyms"]
