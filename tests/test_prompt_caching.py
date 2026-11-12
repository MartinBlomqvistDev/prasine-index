"""Prompt caching: where each Anthropic request carries its cache markers.

The client is a mock that records each request: no network, no API calls.
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from agents import judge_agent, report_agent
from agents.extraction_agent import ExtractionAgent
from agents.judge_agent import JudgeAgent
from agents.report_agent import ReportAgent
from core import model_requests
from core.logger import _JSONFormatter
from ingest import source_document
from models.claim import Claim, ClaimCategory, SourceType

_ONE_HOUR = {"type": "ephemeral", "ttl": "1h"}
_FIVE_MINUTES = {"type": "ephemeral"}


def _response(content: list[Any], stop_reason: str = "tool_use") -> anthropic.types.Message:
    usage = anthropic.types.Usage.model_construct(
        input_tokens=120,
        output_tokens=80,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=4000,
    )
    return anthropic.types.Message.model_construct(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-test",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        stop_details=None,
        usage=usage,
    )


def _tool_use(name: str, tool_input: dict[str, Any]) -> anthropic.types.ToolUseBlock:
    return anthropic.types.ToolUseBlock.model_construct(
        type="tool_use", id="toolu_test", name=name, input=tool_input
    )


def _client(response: anthropic.types.Message) -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


def _requests(client: MagicMock) -> list[dict[str, Any]]:
    return [call.kwargs for call in client.messages.create.call_args_list]


def _markers(blocks: list[dict[str, Any]]) -> list[Any]:
    return [block.get("cache_control") for block in blocks]


class TestJudge:
    """The judge's system prompt and tool are cached for an hour, as one prefix."""

    async def _two_requests(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        prompts = iter(["first claim and its records", "second claim and its records"])
        monkeypatch.setattr(judge_agent, "_build_judge_prompt", lambda _input: next(prompts))
        client = _client(_response([_tool_use("produce_verdict", {"score": 10})]))
        agent = JudgeAgent(client=client, model_id="claude-opus-5-5")
        await agent._call_llm(SimpleNamespace())
        await agent._call_llm(SimpleNamespace())
        return _requests(client)

    async def test_system_prompt_cached_for_an_hour(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = (await self._two_requests(monkeypatch))[0]
        assert _markers(request["system"]) == [_ONE_HOUR]

    async def test_no_shorter_marker_ahead_of_the_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Tools come before the system prompt; a five-minute marker there would be
        # ahead of the one-hour marker, which the API rejects.
        request = (await self._two_requests(monkeypatch))[0]
        assert all("cache_control" not in tool for tool in request["tools"])

    async def test_cached_prefix_is_the_same_for_every_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first, second = await self._two_requests(monkeypatch)
        assert first["messages"] != second["messages"]
        assert first["system"] == second["system"]
        assert first["tools"] == second["tools"]
        assert first["output_config"] == second["output_config"]


class TestReport:
    """The report's system prompt is cached for an hour; the date stays in the message."""

    async def _two_requests(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        prompts = iter(["DATE: 2026-11-12\nfirst case", "DATE: 2026-11-13\nsecond case"])
        monkeypatch.setattr(report_agent, "_with_published_evidence", lambda input: input)
        monkeypatch.setattr(report_agent, "_build_report_prompt", lambda _input: next(prompts))
        text = anthropic.types.TextBlock.model_construct(type="text", text="### The Claim")
        client = _client(_response([text], stop_reason="end_turn"))
        agent = ReportAgent(client=client, model_id="claude-sonnet-5-5")
        case = SimpleNamespace(verification=SimpleNamespace(evidence=[]), score=None)
        await agent._call_llm(case)
        await agent._call_llm(case)
        return _requests(client)

    async def test_system_prompt_cached_for_an_hour(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first, second = await self._two_requests(monkeypatch)
        assert _markers(first["system"]) == [_ONE_HOUR]
        assert first["system"] == second["system"]
        assert "tools" not in first

    def test_system_prompt_has_no_date(self) -> None:
        assert "DATE:" not in report_agent._SYSTEM_PROMPT


class TestExtraction:
    """Extraction caches its tool and system prompt with one lifetime."""

    async def test_tool_and_system_prompt_cached(self) -> None:
        client = _client(_response([_tool_use("extract_green_claims", {"claims": []})]))
        agent = ExtractionAgent(client=client)
        await agent._call_llm("First page.", "Acme")
        await agent._call_llm("Second page.", None)
        first, second = _requests(client)
        assert _markers(first["system"]) == [_FIVE_MINUTES]
        assert _markers(first["tools"]) == [_FIVE_MINUTES]
        # The company name and the page go in the message, after the cached prefix.
        assert first["system"] == second["system"]
        assert first["tools"] == second["tools"]


_PAGE = "https://example.com/climate"
_SUMMARY = {
    "summary": "The page states a net zero target for 2050.",
    "supports_claim": True,
    "confidence": 0.8,
    "missing_plan_elements": [],
}


def _claim(text: str, url: str = _PAGE) -> Claim:
    return Claim(
        trace_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        source_url=url,
        source_type=SourceType.WEBSITE,
        raw_text=text,
        claim_category=ClaimCategory.NET_ZERO_TARGET,
    )


class TestSourceDocument:
    """The claim's own page or PDF is cached; pages chosen per claim are not."""

    @staticmethod
    def _serve(monkeypatch: pytest.MonkeyPatch, content_type: str, body: bytes) -> None:
        async def fetch(_url: str) -> tuple[str, bytes]:
            return content_type, body

        monkeypatch.setattr(source_document, "_fetch_content", fetch)

    @staticmethod
    def _pdf(monkeypatch: pytest.MonkeyPatch, pages: list[str]) -> None:
        async def pages_of(_address: str, _pdf_bytes: bytes) -> list[str]:
            return pages

        monkeypatch.setattr(source_document, "_pdf_page_count", lambda _pdf_bytes: len(pages))
        monkeypatch.setattr(source_document, "_pages_of", pages_of)

    @staticmethod
    async def _blocks(claims: list[Claim]) -> list[list[dict[str, Any]]]:
        client = _client(_response([_tool_use("extract_climate_disclosures", _SUMMARY)]))
        for claim in claims:
            await source_document.fetch_source_document_data(claim, client)
        return [request["messages"][0]["content"] for request in _requests(client)]

    async def test_page_cached_and_the_same_for_every_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = b"<html><body><p>We will reach net zero by 2050. Scope 1 fell 41%.</p></body></html>"
        self._serve(monkeypatch, "text/html", html)
        first, second = await self._blocks(
            [_claim("We will reach net zero by 2050."), _claim("Scope 1 fell 41%.")]
        )
        assert _markers(first) == [_FIVE_MINUTES, None]
        assert first[0] == second[0]
        assert first[-1] != second[-1]

    async def test_linked_document_is_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        html = (
            b"<p>We will reach net zero by 2050.</p>"
            b'<a href="/files/annual-report-2025.pdf">Annual Report 2025</a>'
        )
        self._serve(monkeypatch, "text/html", html)

        async def linked(*_args: Any) -> str:
            return "[PDF page 4] Scope 1 emissions fell 41% against 2019."

        monkeypatch.setattr(source_document, "_read_linked_report", linked)
        (blocks,) = await self._blocks([_claim("We will reach net zero by 2050.")])
        assert "LINKED DOCUMENT" in blocks[1]["text"]
        assert _markers(blocks) == [_FIVE_MINUTES, None, None]

    async def test_short_pdf_cached_with_its_page_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, "application/pdf", b"%PDF-1.7 test")
        self._pdf(monkeypatch, ["Net zero by 2050 for our emissions.", "Scope 1 targets."])
        (blocks,) = await self._blocks([_claim("Net zero by 2050.", _PAGE + "/short.pdf")])
        assert [block["type"] for block in blocks] == ["document", "text", "text"]
        assert blocks[1]["text"].startswith("PAGE MAP")
        assert _markers(blocks) == [None, _FIVE_MINUTES, None]

    async def test_long_pdf_pages_chosen_per_claim_are_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, "application/pdf", b"%PDF-1.7 test")
        self._pdf(monkeypatch, ["Our emissions and net zero target."] * 150)
        (blocks,) = await self._blocks([_claim("Scope 1 fell 41%.", _PAGE + "/long.pdf")])
        assert blocks[0]["text"].startswith("DOCUMENT:")
        assert _markers(blocks) == [None, None]


class TestUsageLogging:
    """Each call logs what was written to and read from the cache."""

    def test_logs_the_cache_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = MagicMock()
        monkeypatch.setattr(model_requests, "logger", logger)
        model_requests.log_usage(_response([]), agent="judge")
        extra = logger.info.call_args.kwargs["extra"]
        assert extra["operation"] == "llm_usage"
        assert extra["input_tokens"] == 120
        assert extra["cache_creation_input_tokens"] == 0
        assert extra["cache_read_input_tokens"] == 4000
        assert "4000 of 4120 prompt tokens read from cache" in logger.info.call_args.args[0]

    def test_missing_cache_fields_count_as_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = MagicMock()
        monkeypatch.setattr(model_requests, "logger", logger)
        response = _response([])
        response.usage.cache_creation_input_tokens = None
        response.usage.cache_read_input_tokens = None
        model_requests.log_usage(response, agent="report")
        extra = logger.info.call_args.kwargs["extra"]
        assert extra["cache_creation_input_tokens"] == 0
        assert extra["cache_read_input_tokens"] == 0

    def test_json_log_line_keeps_the_cache_fields(self) -> None:
        record = logging.LogRecord("core.model_requests", logging.INFO, "", 0, "usage", (), None)
        record.__dict__.update(
            input_tokens=120,
            output_tokens=80,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=4000,
        )
        line = json.loads(_JSONFormatter().format(record))
        assert line["cache_read_input_tokens"] == 4000
        assert line["cache_creation_input_tokens"] == 0
        assert line["input_tokens"] == 120
        assert line["output_tokens"] == 80
