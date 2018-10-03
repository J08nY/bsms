import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from random import choice
from urllib.parse import urlparse, urlunparse

config = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:62.0) Gecko/20100101 Firefox/62.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:62.0) Gecko/20100101 Firefox/62.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.92 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko"
]


def get_user_agent():
    return {"User-Agent": choice(USER_AGENTS)}


def vprint(*args, **kwargs):
    global config
    if config.verbose:
        print(*args, **kwargs)


def get_url_root(url):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


@asyncio.coroutine
def write_segment(segment, out):
    print(".", end="", flush=True)
    out.write(segment.content)


@asyncio.coroutine
def process_segments(segment_futures, out):
    for segment_future in segment_futures:
        segment = yield from segment_future
        yield from asyncio.Task(write_segment(segment, out))


def download_segments(session, urls, out, max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        loop = asyncio.get_event_loop()
        futures = [loop.run_in_executor(executor, session.get, url)
                   for url in urls]
        loop.run_until_complete(process_segments(futures, out))
