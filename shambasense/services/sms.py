"""Outgoing SMS through Africa's Talking. Every message is recorded in sms_log.

Without AT_USERNAME and AT_API_KEY the message is logged as "not_configured" and
nothing is sent, so development and demos never text real people by accident.
The sandbox (AT_USERNAME=sandbox) delivers only to the Africa's Talking simulator.
"""

from __future__ import annotations

import json
import logging

import requests

from .. import config, db

log = logging.getLogger(__name__)
LIVE_URL = "https://api.africastalking.com/version1/messaging"
SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def send(to_phone: str, message: str) -> dict:
    s = config.sms_settings()
    status, response = "not_configured", None
    if s["username"] and s["api_key"] and not config.offline():
        data = {"username": s["username"], "to": to_phone, "message": message}
        if s["sender_id"]:
            data["from"] = s["sender_id"]
        try:
            r = requests.post(SANDBOX_URL if s["sandbox"] else LIVE_URL, data=data, timeout=20,
                              headers={"apiKey": s["api_key"], "Accept": "application/json"})
            response = r.text[:2000]
            recipients = r.json().get("SMSMessageData", {}).get("Recipients", []) if r.ok else []
            status = "sent" if recipients and recipients[0].get("status") == "Success" else "failed"
        except (requests.RequestException, ValueError) as exc:
            status, response = "failed", str(exc)
    with db.session() as sess, sess.begin():
        sess.add(db.SmsLog(to_phone=to_phone, message=message, status=status, provider_response=response))
    if status != "sent":
        log.info("SMS to %s %s", to_phone[:6] + "…", status)
    return {"status": status, "response": json.loads(response) if response and response.startswith("{") else response}
