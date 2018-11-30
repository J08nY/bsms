#!/usr/bin/env python3

# mediasite downloader
# Copyright (c) 2018 Jan Jancar <johny@neuromancer.sk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import argparse
import m3u8
import re
import requests
import subprocess
import tempfile
from PIL import Image
from bs4 import BeautifulSoup
from fpdf import FPDF
from io import BytesIO
from os import makedirs
from os.path import join, exists
from urllib.parse import urlparse, parse_qs

import utils
from utils import vprint, get_user_agent, get_url_root, download_segments, create_session


def get_player_options(vid_url, session):
    vprint("[ ] Getting player options.")
    vid_page = session.get(vid_url)
    vid_soup = BeautifulSoup(vid_page.text, "lxml")
    global_data = vid_soup.find(id="GlobalData")
    res_id = global_data.find(id="ResourceId").string
    service_path = global_data.find(id="ServicePath").string

    req_content = {"getPlayerOptionsRequest": {
        "QueryString": urlparse(vid_url).query,
        "ResourceId": res_id,
        "UrlReferrer": vid_url,
        "UseScreenReader": False
    }
    }
    get_options_svc = get_url_root(
            vid_url) + service_path + "/GetPlayerOptions"
    player_options = session.post(get_options_svc, json=req_content)
    result = player_options.json()
    vprint("[*] Got them.")
    return result


def get_stream_location(stream):
    if stream["StreamType"] == 2:
        # slide stream
        return (stream["SlideBaseUrl"], "slides", len(stream["Slides"]),
                stream["SlideImageFileNameTemplate"])
    else:
        # video stream hopefully
        urls = stream["VideoUrls"]
        result = None
        for vid_url in urls:
            if vid_url["MimeType"] == "video/mp4" and vid_url[
                "MediaType"] == "MP4":
                return (vid_url["Location"], "raw_mp4")
            if vid_url["MimeType"] == "audio/x-mpegurl" and vid_url[
                "MediaType"] == "MP4":
                result = (vid_url["Location"], "manifest_mp4")
        return result


def get_manifests(url, session):
    vprint("[ ] Getting main manifest.")
    manifest = session.get(url)
    vprint("[*] Got it.")
    playlist = m3u8.loads(manifest.text)

    audio_manifest = playlist.playlists[0].uri
    video_manifest = playlist.media[0].uri
    vprint("[*] Got manifests: {}, {}.".format(audio_manifest, video_manifest))
    return audio_manifest, video_manifest


def get_segments(video_base, manifest_name, session):
    vprint("[ ] Getting segments for: {}.".format(manifest_name))
    manifest = session.get(video_base + "/" + manifest_name)
    playlist = m3u8.loads(manifest.text)

    segments = [playlist.segment_map["uri"]] + [segment.uri for segment in
                                                playlist.segments]
    vprint("[*] Got segments.")
    return segments


def get_out_fname(type, base):
    if type == "manifest_mp4" or type == "raw_mp4":
        return base + ".mp4"
    elif type == "slides":
        return base + ".pdf"
    return None


def download_slide_stream(url, other, session, out_fname):
    total = other[2]
    template = other[3]

    template_re = re.compile(r"{0:D(\d+)}")
    width = int(template_re.search(template).group(1))

    template_prefix, _, template_suffix = template_re.split(template)

    slide_files = []
    max_w = 0
    max_h = 0
    for i in range(total):
        slide_name = template_prefix + ("{:0" + str(width) + "d}").format(
                i + 1) + template_suffix
        slide_url = url + slide_name
        vprint("[ ] Downloading slide: {}.".format(slide_url))
        slide = session.get(slide_url)
        img = Image.open(BytesIO(slide.content))
        w, h = img.size
        if w > max_w:
            max_w = w
        if h > max_h:
            max_h = h

        slide_file = tempfile.NamedTemporaryFile(suffix=slide_name)
        slide_file.write(slide.content)
        slide_files.append(slide_file)

    vprint("[ ] Combining pdf.")
    pdf = FPDF("P", "pt", (max_w, max_h))
    for image in slide_files:
        pdf.add_page()
        pdf.image(image.name, 0, 0)
        image.close()
    vprint("[*] Combined.")
    vprint("[ ] Writing pdf.")
    pdf.output(out_fname, "F")
    vprint("[*] Wrote.")


def download_segmented_stream(url, params, other, session, out_fname):
    session.params = params
    audio_manifest, video_manifest = get_manifests(url, session)
    vid_url = url[:url.rfind("/")]
    audio_segments = get_segments(vid_url, audio_manifest, session)
    video_segments = get_segments(vid_url, video_manifest, session)
    with tempfile.NamedTemporaryFile() as aud_file, tempfile.NamedTemporaryFile() as vid_file:
        vprint(
                "[ ] Downloading video segments({})".format(
                        len(video_segments)))
        download_segments(session,
                          (vid_url + "/" + vid_segment for vid_segment in
                           video_segments), vid_file)
        vprint(
                "[ ] Downloading audio segments({}).".format(
                        len(audio_segments)))
        download_segments(session,
                          (vid_url + "/" + aud_segment for aud_segment in
                           audio_segments), aud_file)
        aud_file.flush()
        vid_file.flush()
        vprint("[ ] Joining into {}.".format(out_fname))
        subprocess.call(
                ["ffmpeg", "-i", aud_file.name, "-i", vid_file.name, "-c",
                 "copy", out_fname])
        vprint("[*] Joined to {}.".format(out_fname))


def download_raw_stream(url, params, other, session, out_fname):
    req = session.get(url, params=params, stream=True)
    vprint("[ ] {}.".format(url))
    total = int(req.headers.get("content-length"))
    got = 0
    with open(out_fname, "wb") as out_file:
        for chunk in req.iter_content(chunk_size=1024):
            if chunk:
                out_file.write(chunk)
                if total is not None:
                    amount = ((got * 50) // total)
                    vprint("[{:50}]".format("#" * amount), end="\r")
                    got = got + len(chunk)
    if total is not None:
        vprint()


def download_stream(location, type, other, session, out_file):
    vprint(
            "[ ] Downloading stream({}), {}: {}.".format(type, out_file,
                                                         location))
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    parsed._replace(query="")
    url = parsed.geturl()

    out_fname = get_out_fname(type, out_file)
    if out_fname is None:
        print("[!] Bad type, no out_fname.")
        return
    if exists(out_fname):
        print(
                "[*] Skipping stream({}), because file already exists: {}.".format(
                        type, out_fname))
        return

    if type == "manifest_mp4":
        download_segmented_stream(url, params, other, session, out_fname)
    elif type == "raw_mp4":
        download_raw_stream(url, params, other, session, out_fname)
    elif type == "slides":
        download_slide_stream(url, other, session, out_fname)


def download_lecture(lecture_url, output_name, session):
    print("[ ] Downloading lecture: {} into {}.".format(lecture_url,
                                                        output_name))
    opts = get_player_options(lecture_url, session)
    streams = opts["d"]["Presentation"]["Streams"]
    vprint("[*] Got {} streams.".format(str(len(streams))))
    for i, stream in enumerate(streams):
        stream_data = get_stream_location(stream)
        if stream_data is None:
            print("[!] Cannot find stream to download!")
            return False
        if config.dry_run:
            print("[*] Skipping, because dry-run is enabled.")
            continue
        download_stream(stream_data[0], stream_data[1], stream_data,
                        session, output_name + "_" + str(i))
    print("[*] Downloaded lecture.")
    return True


def download_course(course_url, output_name, session):
    print("[ ] Downloading course: {}.".format(course_url))
    main_page = session.get(course_url)
    main_soup = BeautifulSoup(main_page.text, "lxml")

    main_form = main_soup.find(id="MainForm")
    scripts = main_form.find_all("script")
    catalog_id = None
    catalog_id_re = re.compile(r"CatalogId: *'([a-f0-9\-]+?)'")
    for script in scripts:
        match = catalog_id_re.search(script.string)
        if match:
            catalog_id = match.group(1)

    i = 0
    lecture_urls = []
    total = None
    while len(lecture_urls) != total:
        req_content = {
            "IsViewPage": True,
            "IsNewFolder": False,
            "AuthTicket": None,
            "CatalogId": catalog_id,
            "CurrentFolderId": catalog_id,
            "RootDynamicFolderId": None,
            "ItemsPerPage": 10,
            "PageIndex": i,
            "PermissionMask": "Execute",
            "CatalogSearchType": "SearchInFolder",
            "SortBy": "Date",
            "SortDirection": "Descending",
            "StartDate": None,
            "EndDate": None,
            "StatusFilterList": None,
            "PreviewKey": None,
            "Tags": []
        }
        url = get_url_root(
                course_url) + "/Mediasite/Catalog/Data/GetPresentationsForFolder"

        page = session.post(url, json=req_content)
        page_data = page.json()
        if total is None:
            total = page_data["TotalItems"]
        for lecture in page_data["PresentationDetailsList"]:
            lecture_urls.append((lecture["PlayerUrl"], lecture["Name"]))
        i += 1

    print(
            "[ ] Downloading {} lectures into {}.".format(str(total),
                                                          output_name))
    makedirs(output_name, exist_ok=True)
    for lecture in reversed(lecture_urls):
        fname = join(output_name, lecture[1])
        if not download_lecture(lecture[0], fname, session):
            return False
    return True


def main():
    global config
    parser = argparse.ArgumentParser("mediasite.py",
                                     description="Mediasite video downloader.",
                                     epilog="Licensed under MIT license. Copyright (C) 2018 Jan Jancar")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", "--lecture", dest="lecture_url",
                       help="A URL of a video/lecture to download.")
    group.add_argument("--catalog", "--course", dest="course_url",
                       help="A URL of a catalog/course to download all of its lectures.")
    parser.add_argument("-n", "--dry-run", dest="dry_run", action="store_true",
                        help="Do not download anything.")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument("-a", "--auth", dest="auth", action="store_true",
                        help="Enable authentication, will ask for cookie jar.")
    parser.add_argument("output", type=str,
                        help="Output name, a partial filename in case of a single lecture download, "
                             "or a directory in case of a course download.")
    config = parser.parse_args()
    utils.config = config

    if config.auth:
        cookie_string = input("Gimme the session cookies:")
    else:
        cookie_string = None

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
