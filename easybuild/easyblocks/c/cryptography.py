##
# Copyright 2017-2019 Ghent University
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
EasyBuild support for building and installing cryptography, implemented as an easyblock

@author: Alexander Grund
"""
from easybuild.easyblocks.generic.pythonpackage import PythonPackage


class EB_cryptography(PythonPackage):
    """Support for building/installing cryptography."""

    def __init__(self, *args, **kwargs):
        """Initialize cryptography easyblock."""
        super(EB_cryptography, self).__init__(*args, **kwargs)

        # cryptography compiles a library using pthreads but does not link against it
        # which causes 'undefined symbol: pthread_atfork', see issue #9446
        self.cfg['preinstallopts'] += 'CFLAGS="$CFLAGS -pthread"'
        self.log.info("Adding -pthread to preinstallopts of cryptography. Final value: %s", self.cfg['preinstallopts'])
