"""Rare Username Hunter core: conservative public checks + Telegram Saved Messages.

No bids, payments, wallet access, username claiming, or stealth rate-limit bypass.
Public Fragment HTML is not an API. Unknown means unknown.
"""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import random
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_LOCK = threading.RLock()
_NAME = re.compile(r'^[a-z]{4}$')
_ROOT = Path(os.environ.get('HOME', '/tmp')) / 'rare_hunter'
_ROOT.mkdir(parents=True, exist_ok=True)
_DB = _ROOT / 'private_state.json'
_SESSION = str(_ROOT / 'telegram_account')


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load():
    try:
        return json.loads(_DB.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {'watch': [], 'results': {}, 'last_check': '', 'credentials': {}, 'cursor': 0}


def _save(data):
    tmp = _DB.with_suffix('.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _DB)
    try:
        os.chmod(_DB, 0o600)
    except OSError:
        pass


def _public_state(data):
    return {
        'watch': data.get('watch', []),
        'results': data.get('results', {}),
        'last_check': data.get('last_check', ''),
        'configured': bool(data.get('credentials', {}).get('api_id')),
        'login_hint': data.get('login_hint', 'Not verified'),
        'note': 'Fragment checks are best-effort; UNKNOWN is not free or purchasable.',
    }


def snapshot():
    with _LOCK:
        return json.dumps(_public_state(_load()))


def add(name):
    name = name.strip().lower().lstrip('@')
    if not _NAME.fullmatch(name):
        return json.dumps({'ok': False, 'message': 'Use exactly 4 letters (a-z).'})
    with _LOCK:
        d = _load()
        if name in d['watch']:
            return json.dumps({'ok': False, 'message': '@' + name + ' is already watched.'})
        if len(d['watch']) >= 20:
            return json.dumps({'ok': False, 'message': 'Limit: 20 watched names in this safe version.'})
        d['watch'].append(name)
        _save(d)
    return json.dumps({'ok': True, 'message': 'Added @' + name})


def remove(name):
    name = name.strip().lower().lstrip('@')
    with _LOCK:
        d = _load()
        if name not in d['watch']:
            return json.dumps({'ok': False, 'message': 'Not on watchlist.'})
        d['watch'].remove(name)
        d['results'].pop(name, None)
        _save(d)
    return json.dumps({'ok': True, 'message': 'Removed @' + name})


def suggest():
    # Names are ONLY creative suggestions. Neither availability nor investment value is implied.
    consonants = 'bcdfghjklmnprstvwxyz'
    vowels = 'aeiou'
    rng = random.SystemRandom()
    out = set()
    while len(out) < 12:
        pattern = rng.choice(['CVCV', 'CVCC', 'VCCV'])
        name = ''.join(rng.choice(vowels if c == 'V' else consonants) for c in pattern)
        if len(set(name)) >= 3:
            out.add(name)
    return json.dumps({'suggestions': sorted(out), 'disclaimer': 'Unverified ideas, not available names or price estimates.'})


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.hidden:
            self.hidden -= 1

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def parse_listing_html(name, html):
    """Conservative parser. Only an explicit status field is treated as evidence.

    Prices are advisory. Never signal that a name is freely claimable.
    """
    parser = _VisibleText()
    try:
        parser.feed(html)
    except Exception:
        return {'state': 'UNKNOWN', 'reason': 'Could not parse page'}
    content = re.sub(r'\s+', ' ', ' '.join(parser.parts))
    if not content or any(k in content.lower() for k in
                          ('attention required! | cloudflare', 'checking your browser',
                           'please enable javascript to continue', 'access denied')):
        return {'state': 'UNKNOWN', 'reason': 'Blocked or incomplete page'}

    # Fragment page layout is subject to change. There is no official public listings API.
    # Do not use unlabeled "sold"/"auction" in site-wide navigation as a signal.
    match = re.search(
        r'\b(?:Status|Username status)\s*[:\-]?\s*'
        r'(On auction|For sale|Available|Sold|Taken|Unavailable)\b',
        content, flags=re.I)
    if not match:
        return {'state': 'UNKNOWN', 'reason': 'No explicit listing status found'}

    state = {
        'on auction': 'AUCTION', 'for sale': 'FOR_SALE',
        'available': 'LISTED_AVAILABLE', 'sold': 'SOLD',
        'taken': 'TAKEN', 'unavailable': 'UNAVAILABLE',
    }[match.group(1).lower()]
    out = {'state': state, 'reason': 'Public-page text heuristic; verify on Fragment'}
    # Price only if a label and unit are adjacent. Currency is never converted or guessed.
    price = re.search(
        r'\b(?:Current bid|Minimum bid|Buy now|Price)\s*[:\-]?\s*'
        r'([\d][\d,.]*)\s*(GRAM|TON)\b', content, flags=re.I)
    if price:
        try:
            value = float(price.group(1).replace(',', ''))
            if value > 0:
                out['price'] = value
                out['currency'] = price.group(2).upper()
        except ValueError:
            pass
    return out


def _fetch_listing(name):
    url = 'https://fragment.com/username/' + name
    req = Request(url, headers={
        'User-Agent': 'RareUsernameHunter/1.0 (personal research; moderate requests)',
        'Accept': 'text/html',
    })
    try:
        with urlopen(req, timeout=9) as response:
            if response.status != 200:
                return {'state': 'UNKNOWN', 'reason': 'HTTP ' + str(response.status), 'url': url}
            content = response.read(600_000).decode('utf-8', errors='replace')
            result = parse_listing_html(name, content)
            result['url'] = url
            return result
    except HTTPError as e:
        return {'state': 'UNKNOWN', 'reason': 'Fragment HTTP ' + str(e.code), 'url': url}
    except (URLError, TimeoutError, OSError) as e:
        return {'state': 'UNKNOWN', 'reason': 'Network request failed', 'url': url}


def _credentials(data):
    c = data.get('credentials', {})
    if not c.get('api_id') or not c.get('api_hash'):
        raise ValueError('Set up your Telegram API credentials first.')
    return c


async def _send_message(text, credentials):
    from telethon import TelegramClient
    client = TelegramClient(_SESSION, int(credentials['api_id']), credentials['api_hash'])
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False
        await client.send_message('me', text)
        return True
    finally:
        await client.disconnect()


def begin_login(api_id, api_hash, phone):
    api_id = str(api_id).strip()
    api_hash = str(api_hash).strip()
    phone = phone.strip()
    if not api_id.isdigit() or not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash) or not re.fullmatch(r'\+\d{7,15}', phone):
        return json.dumps({'ok': False, 'message': 'Enter numeric API ID, 32-character API hash, and phone as +countrycode... '})
    with _LOCK:
        d = _load()
        d['credentials'] = {'api_id': int(api_id), 'api_hash': api_hash, 'phone': phone}
        _save(d)
        try:
            result = asyncio.run(_request_code(d['credentials']))
            d = _load()
            d['credentials']['phone_code_hash'] = result
            d['login_hint'] = 'Verification code requested'
            _save(d)
            return json.dumps({'ok': True, 'message': 'Check your official Telegram app for the login code.'})
        except Exception as e:
            return json.dumps({'ok': False, 'message': _safe_error(e)})


async def _request_code(c):
    from telethon import TelegramClient
    client = TelegramClient(_SESSION, int(c['api_id']), c['api_hash'])
    try:
        await client.connect()
        if await client.is_user_authorized():
            return 'already-authorized'
        sent = await client.send_code_request(c['phone'])
        return sent.phone_code_hash
    finally:
        await client.disconnect()


def verify_code(code):
    code = str(code).strip()
    if not re.fullmatch(r'\d{4,8}', code):
        return json.dumps({'ok': False, 'message': 'Enter the numeric code Telegram sent you.'})
    with _LOCK:
        d = _load()
        try:
            c = _credentials(d)
            if not c.get('phone_code_hash'):
                raise ValueError('Request a new login code first.')
            status = asyncio.run(_sign_in_code(c, code))
            d = _load()
            d['login_hint'] = status
            if status == 'Signed in':
                d['credentials'].pop('phone_code_hash', None)
            _save(d)
            return json.dumps({'ok': True, 'message': status})
        except Exception as e:
            return json.dumps({'ok': False, 'message': _safe_error(e)})


async def _sign_in_code(c, code):
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    client = TelegramClient(_SESSION, int(c['api_id']), c['api_hash'])
    try:
        await client.connect()
        if not await client.is_user_authorized():
            try:
                await client.sign_in(phone=c['phone'], code=code, phone_code_hash=c['phone_code_hash'])
            except SessionPasswordNeededError:
                return 'Two-step password needed. Enter it below.'
        return 'Signed in'
    finally:
        await client.disconnect()


def verify_password(password):
    if not password:
        return json.dumps({'ok': False, 'message': 'Password is required.'})
    with _LOCK:
        d = _load()
        try:
            c = _credentials(d)
            asyncio.run(_sign_in_password(c, password))
            d = _load()
            d['credentials'].pop('phone_code_hash', None)
            d['login_hint'] = 'Signed in'
            _save(d)
            return json.dumps({'ok': True, 'message': 'Signed in. Password was not stored.'})
        except Exception as e:
            return json.dumps({'ok': False, 'message': _safe_error(e)})


async def _sign_in_password(c, password):
    from telethon import TelegramClient
    client = TelegramClient(_SESSION, int(c['api_id']), c['api_hash'])
    try:
        await client.connect()
        await client.sign_in(password=password)
    finally:
        await client.disconnect()


def test_alert():
    with _LOCK:
        try:
            c = _credentials(_load())
            ok = asyncio.run(_send_message('Rare Username Hunter is connected. Test alert only.', c))
            return json.dumps({'ok': ok, 'message': 'Test alert sent to Saved Messages.' if ok else 'Not signed in yet.'})
        except Exception as e:
            return json.dumps({'ok': False, 'message': _safe_error(e)})


def _safe_error(e):
    # Never include credentials, passwords, sessions or raw Telegram exceptions in the UI.
    typ = type(e).__name__
    if isinstance(e, ValueError):
        return str(e)[:180]
    known = {
        'PhoneCodeInvalidError': 'Incorrect Telegram code.',
        'PhoneCodeExpiredError': 'Code expired; request a new one.',
        'PasswordHashInvalidError': 'Incorrect two-step password.',
        'FloodWaitError': 'Telegram rate limit. Stop and try later.',
        'ApiIdInvalidError': 'Telegram API ID/hash rejected.',
        'PhoneNumberInvalidError': 'Telegram rejected the phone number.',
    }
    return known.get(typ, 'Operation failed (' + typ + '). Check your connection and retry.')


def check_once():
    """At most 5 public queries per run, at most 1 request per 1.2 seconds.

    No free-name checker: 4-character usernames are collectibles only.
    """
    with _LOCK:
        d = _load()
        names = d.get('watch', [])
        if not names:
            return json.dumps({'ok': True, 'message': 'Watchlist empty.', 'alerts': [], 'checked': []})
        cursor = d.get('cursor', 0) % len(names)
        batch = [names[(cursor+i) % len(names)] for i in range(min(5, len(names)))]
        d['cursor'] = (cursor + len(batch)) % len(names)
        alerts = []
        checked = []
        for idx, name in enumerate(batch):
            if idx:
                time.sleep(1.2)
            result = _fetch_listing(name)
            result['checked_at'] = _utc()
            previous = d['results'].get(name, {})
            # Important: Unknown never means available. Don't notify about blocked pages.
            if result['state'] != 'UNKNOWN':
                old_state = previous.get('state')
                if old_state and old_state != 'UNKNOWN' and old_state != result['state']:
                    if result['state'] in ('AUCTION', 'FOR_SALE', 'LISTED_AVAILABLE'):
                        alerts.append('@' + name + ' changed from ' + old_state + ' to ' + result['state'])
                old_price = previous.get('price')
                if (previous.get('state') != 'UNKNOWN' and isinstance(old_price, (float, int)) and 'price' in result and
                    previous.get('currency') == result.get('currency') and
                    result['price'] < old_price):
                    alerts.append('@' + name + ' observed price drop: ' + str(old_price) +
                                  ' → ' + str(result['price']) + ' ' + result['currency'])
                d['results'][name] = result
            else:
                # Keep previous verified reading, but mark it as stale/unverified now.
                d['results'][name] = dict(previous, state='UNKNOWN', checked_at=result['checked_at'],
                                          reason=result['reason'], url=result['url'])
            checked.append('@' + name + ': ' + result['state'])
        d['last_check'] = _utc()
        _save(d)
        delivered = False
        if alerts:
            try:
                creds = _credentials(d)
                message = 'Rare Username Hunter alert (verify on Fragment before acting):\n' + \
                    '\n'.join(alerts) + '\n\nhttps://fragment.com'
                delivered = asyncio.run(_send_message(message, creds))
            except Exception:
                delivered = False
        return json.dumps({'ok': True, 'checked': checked, 'alerts': alerts,
                           'telegram_delivered': delivered,
                           'message': 'Checked ' + str(len(batch)) +
                           ' names. UNKNOWN results are expected when Fragment blocks access.'})


def sign_out():
    with _LOCK:
        d = _load()
        creds = d.get('credentials', {})
        if creds.get('api_id') and creds.get('api_hash'):
            try:
                asyncio.run(_disconnect_telegram(creds))
            except Exception:
                pass
        d['credentials'] = {}
        d['login_hint'] = 'Signed out'
        _save(d)
        for path in (_SESSION + '.session', _SESSION + '.session-journal'):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        return json.dumps({'ok': True, 'message': 'Telegram session deleted on this device.'})


async def _disconnect_telegram(creds):
    from telethon import TelegramClient
    client = TelegramClient(_SESSION, int(creds['api_id']), creds['api_hash'])
    try:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
    finally:
        await client.disconnect()
