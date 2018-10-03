# bsms
BrightSpace and MediaSite downloader.

## Brightspace
```
usage: brightspace.py [-h] (--lecture LECTURE_URL | --course COURSE_URL) [-n]
                      [-v]
                      output

Brightspace video downloader.

positional arguments:
  output                Output name, a partial filename in case of a single
                        lecture download, or a directory in case of a course
                        download.

optional arguments:
  -h, --help            show this help message and exit
  --lecture LECTURE_URL
                        A URL of a lecture to download.
  --course COURSE_URL   A URL of a course to download all of its lectures.
  -n, --dry-run         Do not download anything.
  -v, --verbose         Enable verbose output.
```

## Mediasite
```
usage: mediasite.py [-h] (--video LECTURE_URL | --catalog COURSE_URL) [-n]
                    [-v]
                    output

Mediasite video downloader.

positional arguments:
  output                Output name, a partial filename in case of a single
                        lecture download, or a directory in case of a course
                        download.

optional arguments:
  -h, --help            show this help message and exit
  --video LECTURE_URL, --lecture LECTURE_URL
                        A URL of a video/lecture to download.
  --catalog COURSE_URL, --course COURSE_URL
                        A URL of a catalog/course to download all of its
                        lectures.
  -n, --dry-run         Do not download anything.
  -v, --verbose         Enable verbose output.
```

