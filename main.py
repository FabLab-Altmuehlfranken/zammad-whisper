import os
import sys
import tempfile
from typing import ByteString, Dict, Optional

import whisper
from zammad_py import ZammadAPI

from flask import Flask
from flask import request
from flask_executor import Executor


app = Flask(__name__)
executor = Executor(app)


def get_zammad_client() -> ZammadAPI:
    zammad_url = os.getenv("ZAMMAD_URL")
    zammad_token = os.getenv("ZAMMAD_TOKEN")

    if zammad_url is None or zammad_token is None:
        print("Missing ZAMMAD_URL/ZAMMAD_TOKEN environment variable", file=sys.stderr)
        exit(1)

    return ZammadAPI(url=f"{zammad_url}/api/v1/", http_token=zammad_token)


def find_audio_attachment(article: Dict) -> Optional[Dict]:
    for attachment in article["attachments"]:
        mime_type = attachment["preferences"]["Mime-Type"]
        if mime_type.startswith("audio") and attachment["size"] != "0":
            return attachment

    return None


def transcribe(audio: ByteString) -> str:
    fd, filename = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "w+b") as f:
            f.write(audio)

        model = whisper.load_model(os.getenv("WHISPER_MODEL", "turbo"))
        result = model.transcribe(filename)

    finally:
        os.remove(filename)

    text = result["text"]
    if isinstance(text, str):
        return text
    return "transcription failed"


def create_comment(zammad: ZammadAPI, ticket_id: int, text: str):
    default_header = "Audio Transcription"
    default_warning = "Automatic transcription may contain errors."
    header = os.getenv("COMMENT_HEADER", default_header)
    warning = os.getenv("COMMENT_WARNING", default_warning)

    params = {
        "ticket_id": ticket_id,
        "body": f"""<h1>{header}</h1>

            <blockquote>{text}</blockquote>
            <p><small>{warning}</small></p>""",
        "content_type": "text/html",
        "type": "note",
        "internal": True,
        "sender": "Agent",
    }

    zammad.ticket_article.create(params)


def process_ticket(ticket):
    attachment = find_audio_attachment(ticket["article"])
    if attachment is None:
        print(f"No valid audio attachment in ticket {ticket['ticket']['number']}")
        return

    zammad = get_zammad_client()
    audio_bytes = zammad.ticket_article_attachment.download(
        id=attachment["id"],
        article_id=ticket["article"]["id"],
        ticket_id=ticket["ticket"]["id"],
    )

    text = transcribe(audio_bytes)
    create_comment(zammad, ticket["ticket"]["id"], text)
    print(f"Added transcription for ticket {ticket['ticket']['number']}")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    executor.submit(process_ticket, data)
    return "lets go"


@app.route("/health")
def health():
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0")
