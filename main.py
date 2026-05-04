import os
import sys
import tempfile
from typing import ByteString, Dict, List, Optional

import requests
import whisper
from zammad_py import ZammadAPI


def get_zammad_client() -> ZammadAPI:
    zammad_url = os.getenv("ZAMMAD_URL")
    zammad_token = os.getenv("ZAMMAD_TOKEN")

    if zammad_url is None or zammad_url is None:
        print("Missing ZAMMAD_URL/ZAMMAD_TOKEN environment variable", file=sys.stderr)
        exit(1)

    return ZammadAPI(url=f"{zammad_url}/api/v1/", http_token=zammad_token)


def get_all_tickets(zammad: ZammadAPI) -> List[Dict]:
    tickets = []

    page = zammad.ticket.all()
    while True:
        for ticket in page:
            tickets.append(ticket)

        if page.is_last_page():
            break
        page = page.next_page()

    return tickets


def filter_tickets(tickets: List[Dict]) -> List[Dict]:
    title = os.getenv("TITLE", "")

    filtered_list = [
        ticket
        for ticket in tickets
        if title in ticket["title"] and ticket["state"] in ("new", "open")
    ]

    return filtered_list


def check_comments(articles: List[Dict]) -> bool:
    header = os.getenv("COMMENT_HEADER", "Audio Transcription")
    return any([True for article in articles if header in article["body"]])


def find_audio_attachment(zammad: ZammadAPI, article: Dict) -> Optional[Dict]:
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


def uptime():
    url = os.getenv("UPTIME_URL")
    if url is None:
        return

    requests.get(url)


def main():
    zammad = get_zammad_client()
    tickets = get_all_tickets(zammad)
    tickets = filter_tickets(tickets)

    for ticket in tickets:
        articles = zammad.ticket.articles(ticket["id"])
        if check_comments(articles):
            print(f"Found existing transcription in ticket {ticket['number']}")
            continue

        attachment = find_audio_attachment(zammad, articles[0])
        if attachment is None:
            print(f"No valid audio attachment in ticket {ticket['number']}")
            continue

        audio_bytes = zammad.ticket_article_attachment.download(
            id=attachment["id"],
            article_id=articles[0]["id"],
            ticket_id=ticket["id"],
        )

        text = transcribe(audio_bytes)
        create_comment(zammad, ticket["id"], text)
        print(f"Added transcription for ticket {ticket['number']}")

    uptime()


if __name__ == "__main__":
    main()
