"""Recognizes a web login form in an HTML page and prepares its submission.

The source (a PHP application) may authenticate with a session started from a
login form rather than -- or in addition to -- HTTP Basic Auth. Instead of
hardcoding field names we have never seen, the form is read from the page the
server itself returns: its action, its hidden fields (CSRF tokens included),
the user field and the password field.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html

_USER_FIELD_HINT = re.compile(r"user|usuario|login|email|correo|nombre|name", re.IGNORECASE)
_SKIPPED_INPUT_TYPES = {"submit", "button", "image", "reset", "file", "password"}


@dataclass(frozen=True)
class LoginForm:
    action: str
    username_field: str
    password_field: str
    fields: dict[str, str] = field(default_factory=dict)

    def payload(self, username: str, password: str) -> dict[str, str]:
        data = dict(self.fields)
        data[self.username_field] = username
        data[self.password_field] = password
        return data


def _input_type(element) -> str:
    return (element.get("type") or "text").strip().lower()


def find_login_form(page_html: str, page_url: str) -> LoginForm | None:
    if "password" not in page_html.lower():
        return None
    try:
        doc = lxml_html.fromstring(page_html)
    except (ValueError, etree.ParserError):
        return None

    for form in doc.xpath("//form"):
        passwords = [i for i in form.xpath(".//input[@name]") if _input_type(i) == "password"]
        if not passwords:
            continue

        fields: dict[str, str] = {}
        text_inputs = []
        for element in form.xpath(".//input[@name]"):
            kind = _input_type(element)
            if kind in ("checkbox", "radio") and element.get("checked") is None:
                continue
            if kind in _SKIPPED_INPUT_TYPES:
                continue
            fields[element.get("name")] = element.get("value") or ""
            if kind in ("text", "email"):
                text_inputs.append(element)
        for select in form.xpath(".//select[@name]"):
            chosen = select.xpath(".//option[@selected]") or select.xpath(".//option")
            fields[select.get("name")] = (chosen[0].get("value") or chosen[0].text_content()).strip() if chosen else ""
        # Some PHP handlers only act when the submit button's name is posted (isset($_POST['login'])).
        buttons = [
            b for b in form.xpath(".//button[@name]|.//input[@name]")
            if (b.tag == "button" and _input_type(b) in ("submit", "text")) or (b.tag == "input" and _input_type(b) == "submit")
        ]
        if buttons:
            fields[buttons[0].get("name")] = buttons[0].get("value") or ""

        if not text_inputs:
            continue
        user = next(
            (i for i in text_inputs if _USER_FIELD_HINT.search(i.get("name") or "") or _USER_FIELD_HINT.search(i.get("id") or "")),
            text_inputs[0],
        )
        return LoginForm(
            action=urljoin(page_url, form.get("action") or page_url),
            username_field=user.get("name"),
            password_field=passwords[0].get("name"),
            fields={k: v for k, v in fields.items() if k not in (user.get("name"), passwords[0].get("name"))},
        )
    return None
