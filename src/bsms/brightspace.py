#!/usr/bin/env python3

# BrightSpace downloader
# Copyright (c) 2018 Jan Jancar <johny@neuromancer.sk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import time
from itertools import islice

import json
import m3u8
import re
import requests
import yaml
from argparse import ArgumentParser
from bs4 import BeautifulSoup
from functools import reduce
from http import cookies
from os import makedirs
from os.path import split, exists
from urllib.parse import urljoin, urlparse

import utils
from utils import vprint, get_user_agent, get_url_root, download_segments


def unix_time():
    return int(round(time.time() * 1000))


def create_session(initial_cookies):
    s = requests.Session()
    cookie = cookies.SimpleCookie()
    cookie.load(initial_cookies)
    s.cookies.update(cookie)
    return s


def download_lecture(lecture_url, output_name, session):
    print(
            "[ ] Downloading lecture {} into {}.".format(lecture_url,
                                                         output_name))

    # Get the root
    full_root = get_url_root(lecture_url)

    # Load the video page.
    vprint("[ ] Get video page.")
    view = session.get(lecture_url)
    view_page = BeautifulSoup(view.text, "lxml")
    # Find the iframe.
    content_view = view_page.find(id="ContentView")
    form_src = content_view.find(class_="d2l-iframe")["src"]

    # Load the iframe (its a form we need to go through).
    vprint("[ ] Get form iframe.")
    form_view = session.get(urljoin(full_root, form_src))
    form_page = BeautifulSoup(form_view.text, "lxml")
    # Parse the form.
    form = form_page.find("form")
    inputs = form_page.find_all("input")

    submit_url = form["action"]
    form_data = {}
    for input in inputs:
        form_data[input["name"]] = input["value"]

    # Use the proper root.
    download_root = get_url_root(submit_url)

    # Submit the form and get actual video iframe.
    vprint("[ ] Submit form iframe.")
    iframe_view = session.post(submit_url, data=form_data)
    iframe_page = BeautifulSoup(iframe_view.text, "lxml")

    # Get the player initialization dict.
    player_javascript = iframe_page.find(
            lambda elem: elem.name == "script" and not elem.has_attr(
                    "src") and "new Player" in elem.string)
    dict_match = re.search("new Player\((.+)\)", player_javascript.string,
                           re.DOTALL)
    player_dict = yaml.load(dict_match.group(1))
    oid = player_dict["media_oid"]

    # Register a session.
    vprint("[ ] Register a session.")
    session.get(urljoin(download_root, "/statistics/get/session/"),
                params={"oid": oid, "_": str(unix_time())})

    # Query the modes.
    vprint("[ ] Get the modes.")
    modes_view = session.get(urljoin(download_root, "/api/v2/medias/modes/"),
                             params={"html5": "webm_ogg_ogv_oga_mp4_mp3_m3u8",
                                     "oid": oid})
    modes = modes_view.json()

    # Get the adaptive playlist.
    vprint("[ ] Get adaptive playlist.")
    adaptive_view = session.get(modes["Auto"]["html5"])
    adaptive = m3u8.loads(adaptive_view.text)

    # Get the best stream.
    max_res = reduce(
            lambda cumul, cur: cumul if cumul.stream_info.resolution[0] >
                                        cur.stream_info.resolution[0] else cur,
            adaptive.playlists)

    # Get its playlist.
    vprint("[ ] Got best stream, resolution={}.".format(
            max_res.stream_info.resolution))
    playlist_view = session.get(max_res.uri)
    resource_base = urljoin(max_res.uri, ".")
    playlist = m3u8.loads(playlist_view.text)

    if config.dry_run:
        return True

    if exists(output_name):
        print(
                "[*] Skipping lecture, because file already exists: {}.".format(
                        output_name))
        return True

    # Get the segments.
    vprint("[ ] Downloading segments({}).".format(len(playlist.segments)))
    with open(output_name, "wb") as out:
        download_segments(session, (urljoin(resource_base, segment.uri)
                                    for segment in playlist.segments), out)
    return True


def download_course(course_url, output_name, session):
    print("[ ] Downloading course {}.".format(course_url))
    # Parse the course url.
    parsed = urlparse(course_url)
    path = split(parsed.path)
    course_id = path[1]
    root = urljoin(course_url, "..")
    full_root = urljoin(root, "..")
    content_home = urljoin(root, "le/content/" + str(course_id) + "/Home")

    # Get the course content home.
    vprint("[ ] Get course home.")
    home_view = session.get(content_home)
    soup = BeautifulSoup(home_view.text, "lxml")

    # Find the videos menu entry.
    videos_link = soup.find(lambda elem: False if elem.string is None else (
            "Video" in elem.string and elem.name == "div"))
    videos_module = next(islice(videos_link.parents, 6, None))
    module_id = videos_module["id"].split("-")[-1]

    # Get the videos module.
    data = {
        "mId": module_id,
        "writeHistoryEntry": 1,
        "_d2l_prc$headingLevel": 2,
        "_d2l_prc$scope": None,
        "_d2l_prc$hasActiveForm": False,
        "isXhr": True,
        "requestId": 2
    }
    module_details = urljoin(root, "le/content/" + str(
            course_id) + "/ModuleDetailsPartial")
    vprint("[ ] Get video module.")
    module_view = session.get(module_details, params=data)
    module_html = json.loads(module_view.text.split(";", 1)[1])["Payload"][
        "Html"]

    # Find the lecture list.
    module_soup = BeautifulSoup(module_html, "lxml")
    lst = module_soup.find(class_="vui-list")
    lectures = lst.find_all("a", class_="d2l-link")

    # Make sure the directory exists.
    makedirs(output_name, exist_ok=True)

    # Download lectures.
    print("[ ] Downloading {} lectures into {}.".format(len(lectures),
                                                        output_name))
    for item in lectures:
        lecture_url = urljoin(full_root, item["href"])
        if not download_lecture(lecture_url, output_name + "/" + item.string,
                                session):
            return False
    return True


def main():
    global config
    parser = ArgumentParser("brightspace.py",
                            description="Brightspace video downloader.",
                            epilog="Licensed under MIT license. Copyright (C) 2018 Jan Jancar")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--lecture", dest="lecture_url",
                       help="A URL of a lecture to download.")
    group.add_argument("--course", dest="course_url",
                       help="A URL of a course to download all of its lectures.")
    parser.add_argument("-n", "--dry-run", dest="dry_run", action="store_true",
                        help="Do not download anything.")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument("output", type=str,
                        help="Output name, a partial filename in case of a single lecture download, "
                             "or a directory in case of a course download.")
    config = parser.parse_args()
    utils.config = config

    cookie_string = input("Gimme the session cookies:")
    with create_session(cookie_string) as session:
        session.headers.update(get_user_agent())

        if config.lecture_url is not None:
            if not download_lecture(config.lecture_url, config.output,
                                    session):
                return 1
        if config.course_url is not None:
            if not download_course(config.course_url, config.output, session):
                return 1

    print("[*] Done!")
    return 0


if __name__ == "__main__":
    exit(main())
