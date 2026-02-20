##
# Copyright 2021-2026  Ghent University
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
Easyconfig for installing a gnupg bundle

The gnupg-bundle is using a UNIX socket path in its tests, specifically for the gpgme component. However, UNIX socket
paths are limited to 108 characters in length. This easyblock ensures that the build directory is located in a path
sufficiently small so that the UNIX sockets for the tests can be created.

Source: https://gitlab.archlinux.org/archlinux/archlinux-wsl/-/issues/10

@author: Georgios Kafanas (University of Luxembourg)
"""

import random
import time
from string import ascii_letters

from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM


class EB_gnupg_minus_bundle(Bundle):
    MAX_UNIX_SOCKET_SAFE_BUILD_PATH_LENGTH = 60

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to gnupg-bundle"""
        extra_vars = Bundle.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'unix_socket_compliant_buildpath': [
                None,
                "A build path that ensures that test UNIX socket paths are less than 108 characters long",
                CUSTOM
            ]
        })
        return extra_vars

    @staticmethod
    def _get_random_build_path(base_path, prefix):
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        salt = ''.join(random.choices(ascii_letters, k=5))
        random_path = f'{base_path}/{prefix}-{timestamp}-{salt}'
        return random_path

    @staticmethod
    def _get_unix_socket_compliant_buildpath(easyblock):
        buildpath = easyblock.cfg['unix_socket_compliant_buildpath']
        if buildpath is None:
            buildpath = EB_gnupg_minus_bundle._get_random_build_path(base_path='/tmp', prefix=easyblock.name)
        if len(buildpath) > EB_gnupg_minus_bundle.MAX_UNIX_SOCKET_SAFE_BUILD_PATH_LENGTH:
            raise EasyBuildError("Build path is too large (>60 chars) for a test Linux socket: "
                                 f"unix_socket_compliant_buildpath = {buildpath}")

        return buildpath

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if len(self.builddir) > EB_gnupg_minus_bundle.MAX_UNIX_SOCKET_SAFE_BUILD_PATH_LENGTH:
            self.builddir = EB_gnupg_minus_bundle._get_unix_socket_compliant_buildpath(self)

            print_msg("using modified build path to ensure test UNIX socket can be created: %s ..." % self.builddir)
            self.log.info("Using modified build path to ensure test UNIX socket can be created: %s", self.builddir)
