import sys
from setuptools import setup, find_packages

PACKAGE = "corenlp"
NAME = "stanford-corenlp-python"
DESCRIPTION = "A Stanford Core NLP wrapper (wordseer fork)"
AUTHOR = "Hiroyoshi Komatsu, Dustin Smith, Aditi Muralidharan"
AUTHOR_EMAIL = "aditi.shrikumar@gmail.com"
URL = "https://github.com/Wordseer/stanford-corenlp-python"
VERSION = "3.3.7-0"
INSTALLATION_REQS = ["unidecode >= 0.04.12", "xmltodict >= 0.4.6"]

PEXPECT = "pexpect >= 2.4"
WINPEXPECT = "winpexpect >= 1.5"

if "win" in sys.platform:
	INSTALLATION_REQS.append(WINPEXPECT)
else:
	INSTALLATION_REQS.append(PEXPECT)

setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    url=URL,
    packages=find_packages(),
    package_data = {"": ["*.properties"],
        "corenlp": ["*.properties"]},
    install_requires=INSTALLATION_REQS,
    classifiers=[
        ("License :: OSI Approved :: GNU General Public License v2 or later "
            "(GPLv2+)"),
        "Programming Language :: Python",
    ],
)

