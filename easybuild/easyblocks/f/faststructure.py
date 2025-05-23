# -*- coding: utf-8 -*-
##
# Copyright 2009-2025 Ghent University
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
import stat

from easybuild.easyblocks.generic.cmdcp import CmdCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import adjust_permissions, change_dir, read_file, write_file
from easybuild.tools.run import run_shell_cmd


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
        super().__init__(*args, **kwargs)

        self.cfg['files_to_copy'] = ['*']
        self.pyfiles = ['distruct.py', 'chooseK.py', 'structure.py']
        # custom path-like environment variables for RepeatMaskerConfig
        self.module_load_environment.PATH = ['']

    def build_step(self):
        """Build fastStructure using setup.py."""
        cwd = change_dir('vars')
        run_shell_cmd("python setup.py build_ext --inplace")
        change_dir(cwd)
        run_shell_cmd("python setup.py build_ext --inplace")

    def post_processing_step(self):
        """Add a shebang to the .py files and make them executable."""
        for pyfile in self.pyfiles:
            pf_path = os.path.join(self.installdir, pyfile)
            pf_contents = read_file(pf_path)
            write_file(pf_path, "#!/usr/bin/env python\n" + pf_contents)
            adjust_permissions(pf_path, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        super().post_processing_step()

    def sanity_check_step(self):
        """Custom sanity check for fastStructure."""
        custom_paths = {
            'files': self.pyfiles,
            'dirs': ['vars'],
        }
        super().sanity_check_step(custom_paths=custom_paths)
