##
# Copyright 2018-2024 Free University of Brussels
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
@author: Ward Poelmans (Free University of Brussels)
"""
import glob
import os
import stat

from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, change_dir
from easybuild.tools.filetools import copy_file, write_file
from easybuild.tools.modules import get_software_root


class EB_BWISE(MakeCp):
    """
    Custom easyblock to install BWISE
    """
    @staticmethod
    def extra_options():
        """Change default values of options"""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def build_step(self):
        """Run multiple times for different sources"""

        # BCALM is a git submodule of BWISE but we use it as a dependency because
        # it also has submodules and it's from a different developer
        bcalm = get_software_root('BCALM')
        if not bcalm:
            raise EasyBuildError("BWISE needs BCALM to work")

        makefiles_fixes = [
            (r'^CC=.*$', 'CC=$(CXX)'),
            (r'^CFLAGS=.*$', 'CFLAGS:=$(CFLAGS)'),
            (r'^LDFLAGS=.*$', 'LDFLAGS:=$(LDFLAGS) -fopenmp')
        ]

        def find_build_subdir(pattern):
            """Changes to the sub directory that matches the given pattern"""
            subdir = glob.glob(os.path.join(self.builddir, pattern))
            if subdir:
                change_dir(subdir[0])
                apply_regex_substitutions('makefile', makefiles_fixes)
                super(EB_BWISE, self).build_step()
                return subdir[0]
            else:
                raise EasyBuildError("Could not find a subdirectory matching the pattern %s", pattern)

        # BWISE has 3 independant parts, we build them one by one
        # first BWISE itself
        subdir = find_build_subdir(os.path.join('BWISE-*', 'src'))
        apply_regex_substitutions(os.path.join(subdir, '..', 'Bwise.py'),
                                  [(r'^BWISE_MAIN = .*$', 'BWISE_MAIN = os.environ[\'EBROOTBWISE\']')])

        # Onwards to BGREAT
        subdir = find_build_subdir('BGREAT2-*')
        copy_file(os.path.join(subdir, 'bgreat'), self.cfg['start_dir'])

        # Finally, BTRIM
        subdir = find_build_subdir('BTRIM-*')
        copy_file(os.path.join(subdir, 'btrim'), self.cfg['start_dir'])

        binaries = ['sequencesToNumbers', 'numbersFilter', 'path_counter', 'maximal_sr', 'simulator',
                    'path_to_kmer', 'K2000/*.py', 'K2000/*.sh']
        self.cfg['files_to_copy'] = [(['bgreat', 'btrim', 'Bwise.py'] + ['src/%s' % x for x in binaries], 'bin'),
                                     'data']

    def install_step(self):
        super(EB_BWISE, self).install_step()

        # BWISE expects BCALM to be at exactly this location...
        bcalmwrapper = """#!/bin/sh
$EBROOTBCALM/bin/bcalm "$@"
        """
        write_file(os.path.join(self.installdir, "bin", "bcalm"), bcalmwrapper)

        adjust_permissions(os.path.join(self.installdir, "bin"), stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def sanity_check_step(self):
        """Custom sanity check for BWISE."""
        custom_paths = {
            'files': [os.path.join('bin', x) for x in ['bcalm', 'Bwise.py', 'bgreat', 'btrim']],
            'dirs': ['data']
        }
        super(EB_BWISE, self).sanity_check_step(custom_paths=custom_paths)
