"""Model, paths, and run limits for the Campus Customs agent team.

PORTKEY_API_KEY comes from hw5/.env (copy .env.example), falling back to the course-root .env.
Never print, log, or return it.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

BACKEND_DIR = Path(__file__).resolve().parent
HW5_DIR = BACKEND_DIR.parent
load_dotenv(HW5_DIR / ".env")  # this repo (copy .env.example to .env)
load_dotenv(HW5_DIR.parent / ".env")  # course root, if the repo sits inside the course folder

MODEL_NAME = "gpt-6-luna"  # the only model any agent uses
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

PROMPTS_DIR = BACKEND_DIR / "prompts"
AUDIT_PATH = HW5_DIR / "output" / "audit_trail.json"
MCP_SERVER = HW5_DIR / "mcp_server" / "server.py"
MCP_PYTHON = sys.executable  # same interpreter as the backend, so FastMCP is importable

# Token guardrails. One budget is shared by the whole team for a single top-level run:
# delegated agents draw from the same counters, so a delegation chain can't multiply the spend.
RUN_LIMITS = UsageLimits(request_limit=40, tool_calls_limit=80, total_tokens_limit=250_000)
# Per response. Reasoning tokens count toward max_tokens, so keep reasoning effort low.
MODEL_SETTINGS = OpenAIResponsesModelSettings(max_tokens=8_000, openai_reasoning_effort="low")
MAX_DELEGATION_DEPTH = 3  # boss -> accounting -> facilities is depth 2; one more hop allowed
MAX_DELEGATIONS_PER_RUN = 10
AUDIT_TEXT_LIMIT = 2_000  # characters kept per tool result / model text in the audit trail


@lru_cache(maxsize=1)
def build_model() -> OpenAIResponsesModel:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing. Put it in the course-root .env.")
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-provider": "openai"})
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
