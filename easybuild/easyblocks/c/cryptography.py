##
# Copyright 2017-2025 Ghent University
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
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.run import run_shell_cmd


class EB_cryptography(PythonPackage):
    """Support for building/installing cryptography."""

    def __init__(self, *args, **kwargs):
        """Initialize cryptography easyblock."""
        super(EB_cryptography, self).__init__(*args, **kwargs)

        # cryptography compiles a library using pthreads but does not link against it
        # which causes 'undefined symbol: pthread_atfork'
        # see https://github.com/easybuilders/easybuild-easyconfigs/issues/9446
        # and upstream: https://github.com/pyca/cryptography/issues/5084
        self.cfg['prebuildopts'] += 'CFLAGS="$CFLAGS -pthread"'
        self.cfg['preinstallopts'] += 'CFLAGS="$CFLAGS -pthread"'
        self.log.info("Adding -pthread to prebuildopts & preinstallopts of cryptography.\n" +
                      "Final values: prebuildopts=%s and preinstallopts=%s",
                      self.cfg['prebuildopts'],
                      self.cfg['preinstallopts'])

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check"""
        success, fail_msg = super(EB_cryptography, self).sanity_check_step(*args, **kwargs)
        if success:
            # Check module added in v0.7 leading to issue #9446 (see above)
            if LooseVersion(self.version) >= LooseVersion("0.7"):
                run_shell_cmd("python -s -c 'from cryptography.hazmat.bindings.openssl import binding'")
        return success, fail_msg
