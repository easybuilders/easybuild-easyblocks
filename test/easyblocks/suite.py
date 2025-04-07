#!/usr/bin/python
##
# Copyright 2012-2025 Ghent University
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
This script is a collection of all the testcases for easybuild-easyblocks.
Usage: "python -m test.easyblocks.suite" or "python test/easyblocks/suite.py"

@author: Toon Willems (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import shutil
import sys
import tempfile
import unittest

from easybuild.base import fancylogger
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.options import set_tmpdir

import test.easyblocks.easyblock_specific as e
import test.easyblocks.general as g
import test.easyblocks.init_easyblocks as i
import test.easyblocks.module as m

# initialize logger for all the unit tests
fd, log_fn = tempfile.mkstemp(prefix='easybuild-easyblocks-tests-', suffix='.log')
os.close(fd)
os.remove(log_fn)
fancylogger.logToFile(log_fn)
log = fancylogger.getLogger()
log.setLevelName('DEBUG')

try:
    tmpdir = set_tmpdir(raise_error=True)
except EasyBuildError as err:
    sys.stderr.write("No execution rights on temporary files, specify another location via $TMPDIR: %s\n" % err)
    sys.exit(1)

os.environ['EASYBUILD_TMP_LOGDIR'] = tempfile.mkdtemp(prefix='easyblocks_test_')

# call suite() for each module and then run them all
SUITE = unittest.TestSuite([x.suite() for x in [g, i, m, e]])
res = unittest.TextTestRunner().run(SUITE)

fancylogger.logToFile(log_fn, enable=False)
shutil.rmtree(os.environ['EASYBUILD_TMP_LOGDIR'])
del os.environ['EASYBUILD_TMP_LOGDIR']

if not res.wasSuccessful():
    sys.stderr.write("ERROR: Not all tests were successful.\n")
    print("Log available at %s" % log_fn)
    sys.exit(2)
else:
    for f in glob.glob('%s*' % log_fn):
        os.remove(f)
    shutil.rmtree(tmpdir)
