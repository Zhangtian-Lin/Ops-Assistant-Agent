"""LLM provider abstraction. It parses intent; it never authorizes tools."""

from core.llm.client import LLMClient, LLMResult, load_llm_config

__all__ = ["LLMClient", "LLMResult", "load_llm_config"]
