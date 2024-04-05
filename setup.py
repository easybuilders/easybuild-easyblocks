##
# Copyright 2012-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##

"""
This script can be used to install easybuild-easyblocks, e.g. using:
  easy_install --user .
or
  python setup.py --prefix=$HOME/easybuild

@author: Kenneth Hoste (Ghent University)
"""

import os
import sys
from distutils import log
from distutils.core import setup

sys.path.append('easybuild')
from easyblocks import VERSION  # noqa

FRAMEWORK_MAJVER = str(VERSION).split('.')[0]

# log levels: 0=WARN (default), 1=INFO, 2=DEBUG
log.set_verbosity(1)


# Utility function to read README file
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


log.info("Installing version %s (required versions: API >= %s)" % (VERSION, FRAMEWORK_MAJVER))

setup(
    name="easybuild-easyblocks",
    version=str(VERSION),
    author="EasyBuild community",
    author_email="easybuild@lists.ugent.be",
    description="""Python modules which implement support for installing particular \
 (groups of) software packages with EasyBuild.""",
    license="GPLv2",
    keywords="software build building installation installing compilation HPC scientific",
    url="https://easybuild.io",
    packages=["easybuild", "easybuild.easyblocks", "easybuild.easyblocks.generic"],
    package_dir={"easybuild.easyblocks": "easybuild/easyblocks"},
    package_data={'easybuild.easyblocks': ["[a-z0-9]/*.py"]},
    long_description=read("README.rst"),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Build Tools",
    ],
    platforms="Linux",
    requires=["easybuild_framework(>=%s.0)" % FRAMEWORK_MAJVER],
)
