# -*- coding: utf-8 -*-
##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for building and installing fastStructure, implemented as an easyblock

@author: Bob Dröge (University of Groningen)
"""
import os

from easybuild.easyblocks.generic.cmdcp import CmdCp
from easybuild.framework.easyconfig import CUSTOM


class EB_fastStructure(CmdCp):
    """Support for building and installing fastStructure."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = CmdCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for fastStructure."""
        super(EB_fastStructure, self).__init__(*args, **kwargs)

        self.pyfiles = ['distruct.py', 'chooseK.py', 'structure.py']

    def build_step(self):
        """Build fastStructure using setup.py."""
        self.cfg['cmds_map'] = [
            ('.*', 'cd vars && python setup.py build_ext --inplace && cd .. && python setup.py build_ext --inplace')
        ]
        super(EB_fastStructure, self).build_step()

    def install_step(self):
        """Custom installation procedure for fastStructure."""
        self.cfg['files_to_copy'] = ['*']
        super(EB_fastStructure, self).install_step()

    def post_install_step(self):
        """Add a shebang to the .py files and make them executable."""
        try:
            for pyfile in self.pyfiles:
                with open(os.path.join(self.installdir, pyfile), 'r+') as pf:
                    pf_contents = pf.read()
                    pf.seek(0, 0)
                    pf.write('#!/usr/bin/env python\n' + pf_contents)
                os.chmod(os.path.join(self.installdir, pyfile), 0o755)
        except OSError, err:
            raise EasyBuildError("Failed to patch .py files: %s", err)

    def sanity_check_step(self):
        """Custom sanity check for fastStructure."""
        custom_paths = {
            'files': self.pyfiles,
            'dirs': ['vars'],
        }
        super(EB_fastStructure, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Make sure PATH is set correctly."""
        return {
            'PATH': ['.'],
        }
