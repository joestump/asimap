#!/usr/bin/env python
#

from distutils.core import setup
from asimap import __version__

setup(
    name = 'asimap',
    version = __version__,
    description = 'A pure python based IMAP server using mailbox store',
    long_description = 'asimap is a python based IMAP server using local file stores, like MH as the mail store.',
    author = 'Scanner',
    author_email = 'scanner@apricot.com',
    # url = 'http://github.com/asimap',
    # download_url = 'http://github.com/asimap/download',
    packages = ["asimap"],
    )
