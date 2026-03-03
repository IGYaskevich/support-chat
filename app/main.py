from __future__ import annotations

import re
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from app.config import load_config
from app.safe_support_agent import SafeSupportAgent, detect_language
from app.state_store import StateStore

config = load_config()
store = StateStore(config.state_file)
agent = SafeSupportAgent(config)
validator = RequestValidator(config.twilio_auth_token)

app = FastAPI(title="support-mvp-fastapi")


def _build_twiml_message(text: str) -> str:
    twiml = MessagingResponse()
    twiml.message(text)
    return str(twiml)


def _to_safe_reply_length(text: str) -> str:
    max_len = 3500
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _contains_sensitive_payload(text: str) -> bool:
    has_card_like_number = bool(re.search(r"(?:\d[ -]*?){13,19}", text or ""))
    has_secret_keywords = bool(
        re.search(
            r"(cvv|cvc|otp|sms[\s-]?code|verification[\s-]?code|парол|password|token|токен)",
            text or "",
            re.IGNORECASE,
        )
    )
    return has_card_like_number or has_secret_keywords


def _build_sensitive_data_warning(language: str) -> str:
    if language == "en":
        return "\n".join(
            [
                "Please remove sensitive data from your message.",
                "Do not share full card number, CVV, passwords, SMS codes, or tokens.",
                "Send a sanitized message and I will continue.",
            ]
        )

    if language == "kk":
        return "\n".join(
            [
                "Хабарламаңыздан құпия деректерді алып тастаңыз.",
                "Карта нөмірін толық, CVV, құпиясөз, SMS-код немесе токен жібермеңіз.",
                "Тазартылған нұсқасын жіберіңіз, жалғастырамын.",
            ]
        )

    return "\n".join(
        [
            "Пожалуйста, удалите чувствительные данные из сообщения.",
            "Не отправляйте полный номер карты, CVV, пароли, SMS-коды и токены.",
            "Пришлите обезличенный текст, и я продолжу.",
        ]
    )


def _build_fallback_message(language: str) -> str:
    if language == "en":
        return "Temporary error. Please try again in a minute."
    if language == "kk":
        return "Уақытша қате. 1 минуттан кейін қайталап көріңіз."
    return "Временная ошибка. Повторите запрос через 1 минуту."


def _sanitize_error_message(raw_message: str) -> str:
    message = raw_message or ""
    message = re.sub(r"sk-[^\s\"']+", "[REDACTED_OPENAI_KEY]", message)
    message = re.sub(
        r"(token|secret|password)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        message,
        flags=re.IGNORECASE,
    )
    return message


def _resolve_validation_url(request: Request) -> str:
    if config.public_base_url:
        base = config.public_base_url[:-1] if config.public_base_url.endswith("/") else config.public_base_url
        url = f"{base}{request.url.path}"
        if request.url.query:
            url = f"{url}?{request.url.query}"
        return url

    return str(request.url)


async def _read_incoming_fields(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").lower()

    if "application/x-www-form-urlencoded" in content_type:
        body = (await request.body()).decode("utf-8", errors="ignore")
        return {k: v for k, v in parse_qsl(body, keep_blank_values=True)}

    if "application/json" in content_type:
        payload = await request.json()
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items()}

    form = await request.form()
    return {str(k): str(v) for k, v in form.items()}


def _validate_twilio_signature(request: Request, fields: dict[str, str]) -> bool:
    if not config.twilio_validate_signature:
        return True

    signature = request.headers.get("x-twilio-signature", "")
    validation_url = _resolve_validation_url(request)
    return validator.validate(validation_url, fields, signature)


def _validate_twilio_account_sid(fields: dict[str, str]) -> bool:
    if not config.twilio_validate_signature:
        return True

    if not config.twilio_account_sid:
        return True

    return fields.get("AccountSid", "").strip() == config.twilio_account_sid


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    fields = await _read_incoming_fields(request)

    if not _validate_twilio_signature(request, fields):
        return JSONResponse({"error": "Invalid Twilio signature"}, status_code=403)

    if not _validate_twilio_account_sid(fields):
        return JSONResponse({"error": "Invalid Twilio account sid"}, status_code=403)

    from_phone = fields.get("From", "").strip()
    message = fields.get("Body", "").strip()
    language = detect_language(message)

    if not from_phone or not message:
        text = {
            "en": "Empty message. Please send your question.",
            "kk": "Хабарлама бос. Сұрағыңызды жіберіңіз.",
        }.get(language, "Пустое сообщение. Пришлите ваш вопрос.")
        return Response(_build_twiml_message(text), media_type="text/xml")

    if _contains_sensitive_payload(message):
        warning = _build_sensitive_data_warning(language)
        return Response(_build_twiml_message(warning), media_type="text/xml")

    try:
        user_state = store.get_user(from_phone) or {}
        previous_response_id = str(user_state.get("previousResponseId", ""))

        result = await agent.answer(
            phone=from_phone,
            message=message,
            previous_response_id=previous_response_id,
        )

        store.set_user(
            from_phone,
            {
                "previousResponseId": result.get("response_id", ""),
                "lastIssueId": result.get("issue_id") or user_state.get("lastIssueId", ""),
            },
        )

        return Response(
            _build_twiml_message(_to_safe_reply_length(result.get("text", ""))),
            media_type="text/xml",
        )
    except Exception as error:
        print(f"Webhook processing failed: {_sanitize_error_message(str(error))}")
        return Response(_build_twiml_message(_build_fallback_message(language)), media_type="text/xml")
