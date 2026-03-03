from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import AppConfig
from app.issue_tracker import register_issue
from app.support_instructions import SAFE_SUPPORT_INSTRUCTIONS

ALLOWED_CATEGORIES = {
    "knowledge_gap",
    "content_conflict",
    "account_access",
    "payment_issue",
    "booking_issue",
    "security_incident",
    "broken_link",
    "other",
}
ALLOWED_SEVERITIES = {"P1", "P2", "P3"}
ALLOWED_LANGUAGES = {"ru", "en", "kk"}


def _get_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def detect_language(text: str) -> str:
    if re.search(r"[әғқңөұүһі]", text, re.IGNORECASE):
        return "kk"
    if re.search(r"[а-яё]", text, re.IGNORECASE):
        return "ru"
    return "en"


def build_operator_review_message(language: str) -> str:
    if language == "en":
        return "Operator review is required."
    if language == "kk":
        return "Оператор тексеруі қажет."
    return "Нужна проверка оператором."


def _safe_json_parse(input_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(input_text)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        return {}


def _to_array_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def normalize_issue_payload(raw_payload: dict[str, Any], user_question: str) -> dict[str, Any]:
    inferred_language = detect_language(user_question)
    payload = raw_payload if isinstance(raw_payload, dict) else {}

    category = payload.get("category")
    if category not in ALLOWED_CATEGORIES:
        category = "other"

    severity = payload.get("severity")
    if severity not in ALLOWED_SEVERITIES:
        severity = "P1" if category == "security_incident" else "P2"

    user_language = payload.get("user_language")
    if user_language not in ALLOWED_LANGUAGES:
        user_language = inferred_language

    return {
        "title": str(payload.get("title") or "Support issue from WhatsApp"),
        "category": category,
        "severity": severity,
        "user_language": user_language,
        "user_question": str(payload.get("user_question") or user_question),
        "matched_faq_ids": _to_array_of_strings(payload.get("matched_faq_ids")),
        "summary": str(payload.get("summary") or "No summary provided"),
        "user_impact": str(payload.get("user_impact") or "User impact is not specified"),
        "suggested_next_step": str(
            payload.get("suggested_next_step")
            or "Operator should review conversation and respond"
        ),
    }


def _extract_output_text(response: Any) -> str:
    output_text = _get_attr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = _get_attr(response, "output", []) or []
    chunks: list[str] = []

    for item in output:
        if _get_attr(item, "type") != "message":
            continue
        content = _get_attr(item, "content", []) or []
        for part in content:
            if _get_attr(part, "type") == "output_text":
                text = _get_attr(part, "text", "")
                if isinstance(text, str) and text:
                    chunks.append(text)

    return "\n".join(chunks).strip()


def _get_function_calls(response: Any) -> list[Any]:
    output = _get_attr(response, "output", []) or []
    return [item for item in output if _get_attr(item, "type") == "function_call"]


def _build_issue_line(language: str, issue_id: str) -> str:
    if language == "en":
        return f"Escalated to support: #{issue_id}"
    if language == "kk":
        return f"Қолдауға жіберілді: #{issue_id}"
    return f"Передано в поддержку: #{issue_id}"


def _build_tools(config: AppConfig) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []

    if config.faq_vector_store_id:
        tools.append(
            {
                "type": "file_search",
                "vector_store_ids": [config.faq_vector_store_id],
                "max_num_results": 8,
            }
        )

    tools.append(
        {
            "type": "function",
            "name": "register_issue",
            "description": "Register a support issue when escalation is mandatory by policy.",
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "knowledge_gap",
                            "content_conflict",
                            "account_access",
                            "payment_issue",
                            "booking_issue",
                            "security_incident",
                            "broken_link",
                            "other",
                        ],
                    },
                    "severity": {"type": "string", "enum": ["P1", "P2", "P3"]},
                    "user_language": {"type": "string", "enum": ["ru", "en", "kk"]},
                    "user_question": {"type": "string"},
                    "matched_faq_ids": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "user_impact": {"type": "string"},
                    "suggested_next_step": {"type": "string"},
                },
                "required": [
                    "title",
                    "category",
                    "severity",
                    "user_language",
                    "user_question",
                    "matched_faq_ids",
                    "summary",
                    "user_impact",
                    "suggested_next_step",
                ],
            },
        }
    )

    return tools


class SafeSupportAgent:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = AsyncOpenAI(api_key=config.openai_api_key)
        self.tools = _build_tools(config)

    async def answer(
        self,
        *,
        phone: str,
        message: str,
        previous_response_id: str,
    ) -> dict[str, str]:
        user_language = detect_language(message)

        if not self.config.faq_vector_store_id:
            return {
                "text": build_operator_review_message(user_language),
                "response_id": previous_response_id or "",
                "issue_id": "",
            }

        response = await self.client.responses.create(
            model=self.config.openai_model,
            instructions=SAFE_SUPPORT_INSTRUCTIONS,
            input=message,
            previous_response_id=previous_response_id or None,
            tools=self.tools,
            tool_choice="auto",
            temperature=0.1,
            store=True,
            user=phone,
        )

        issue_id = ""
        register_issue_called = False
        faq_data_missing = False

        for _ in range(self.config.max_tool_iterations):
            calls = _get_function_calls(response)
            if not calls:
                break

            tool_outputs: list[dict[str, str]] = []

            for call in calls:
                call_name = _get_attr(call, "name", "")
                call_id = _get_attr(call, "call_id", "")

                if call_name != "register_issue":
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(
                                {
                                    "status": "error",
                                    "reason": f"Unknown function: {call_name}",
                                }
                            ),
                        }
                    )
                    continue

                if register_issue_called:
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(
                                {
                                    "status": "ignored",
                                    "reason": "register_issue already called for this case",
                                }
                            ),
                        }
                    )
                    continue

                register_issue_called = True
                parsed_args = _safe_json_parse(str(_get_attr(call, "arguments", "{}")))
                issue_payload = normalize_issue_payload(parsed_args, message)
                if len(issue_payload["matched_faq_ids"]) == 0:
                    faq_data_missing = True

                issue_result = await register_issue(issue_payload, self.config)
                if issue_result.get("issue_id"):
                    issue_id = str(issue_result["issue_id"])

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(issue_result, ensure_ascii=False),
                    }
                )

            response = await self.client.responses.create(
                model=self.config.openai_model,
                previous_response_id=_get_attr(response, "id", None),
                input=tool_outputs,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.1,
                store=True,
                user=phone,
            )

        text = _extract_output_text(response)
        if not text:
            text = build_operator_review_message(user_language)

        operator_review_message = build_operator_review_message(user_language)
        if faq_data_missing and operator_review_message.lower() not in text.lower():
            text = f"{text}\n\n{operator_review_message}"

        if issue_id and f"#{issue_id}" not in text:
            text = f"{text}\n\n{_build_issue_line(user_language, issue_id)}"

        return {
            "text": text,
            "response_id": str(_get_attr(response, "id", "")),
            "issue_id": issue_id,
        }
