##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing Stata, implemented as an easyblock

author: Kenneth Hoste (HPC-UGent)
"""
import os
import re

from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.filetools import change_dir
from easybuild.tools.run import run_cmd, run_cmd_qa


class EB_Stata(PackedBinary):
    """Support for building/installing Stata."""

    def install_step(self):
        """Custom install procedure for Stata."""

        change_dir(self.installdir)

        cmd = os.path.join(self.cfg['start_dir'], 'install')
        std_qa = {
            r"Do you wish to continue\?\s*\(y/n or q to quit\)": 'y',
            r"Are you sure you want to install into .*\?\s*\(y/n or q\)": 'y',
            r"Okay to proceed\s*\(y/n or q to quit\)": 'y',
        }
        no_qa = [
            "About to proceed with installation:",
            "uncompressing files",
            "extracting files",
            "setting permissions",
        ]
        run_cmd_qa(cmd, {}, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True)

        print_msg("Note: you need to manually run ./stinit in %s to initialise the license for Stata!",
                  self.installdir)

    def sanity_check_step(self):
        """Custom sanity check for Stata."""
        custom_paths = {
            'files': ['stata', 'xstata'],
            'dirs': [],
        }
        super(EB_Stata, self).sanity_check_step(custom_paths=custom_paths)

        # make sure required libpng library is there for Stata
        # Stata depends on a very old version of libpng, so we need to provide it
        out, _ = run_cmd("ldd %s" % os.path.join(self.installdir, 'stata'), simple=False)
        regex = re.compile('libpng.*not found', re.M)
        if regex.search(out):
            raise EasyBuildError("Required libpng library for 'stata' is not available")
