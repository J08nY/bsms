import os

from setuptools import setup

setup(
        name="bsms",
        author='Jan Jancar',
        author_email='johny@neuromancer.sk',
        version="0.1.0",
        license="MIT",
        install_requires=["requests",
                          "beautifulsoup4",
                          "lxml",
                          "pyaml",
                          "m3u8",
                          "fpdf",
                          "pillow"],
        packages=["bsms"],
        package_dir={'': 'src'},
        entry_points={
            "console_scripts": [
                "brightspace = bsms.brightspace",
                "mediasite = bsms.mediasite"
            ]
        },
        description="Python BrightSpace & MediaSite content downloader",
        long_description=open(
                os.path.join(os.path.dirname(__file__), "README.md")).read()
)
