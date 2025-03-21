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
EasyBuild support for CPLEX, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
from easybuild.tools import LooseVersion
import glob
import os
import stat

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.binary import Binary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, change_dir, mkdir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd


class EB_CPLEX(Binary):
    """
    Support for installing CPLEX.
    Version 12.2 has a self-extracting binary with a Java installer
    """

    def __init__(self, *args, **kwargs):
        """Initialize CPLEX-specific variables."""
        super(EB_CPLEX, self).__init__(*args, **kwargs)

        self.bindir = None
        self.with_python = False
        self.multi_python = 'Python' in self.cfg['multi_deps']

        # Bypass the .mod file check for GCCcore installs
        self.cfg['skip_mod_files_sanity_check'] = True

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""
        super(EB_CPLEX, self).prepare_step(*args, **kwargs)

        if get_software_root('Python'):
            self.with_python = True

    def install_step(self):
        """CPLEX has an interactive installer, so use Q&A"""

        tmpdir = os.path.join(self.builddir, 'tmp')
        stagedir = os.path.join(self.builddir, 'staged')
        change_dir(self.builddir)
        mkdir(tmpdir)
        mkdir(stagedir)

        env.setvar('IATEMPDIR', tmpdir)
        dst = os.path.join(self.builddir, self.src[0]['name'])

        cmd = "%s -i console" % dst

        qa = [
            (r"PRESS <ENTER> TO CONTINUE:", ''),
            (r'Press Enter to continue viewing the license agreement, or enter'
             r' "1" to accept the agreement, "2" to decline it, "3" to print it,'
             r' or "99" to go back to the previous screen\.:', '1'),
            (r'ENTER AN ABSOLUTE PATH, OR PRESS <ENTER> TO ACCEPT THE DEFAULT :', self.installdir),
            (r'IS THIS CORRECT\? \(Y/N\):', 'y'),
            (r'PRESS <ENTER> TO INSTALL:', ''),
            (r"PRESS <ENTER> TO EXIT THE INSTALLER:", ''),
            (r"CHOOSE LOCALE BY NUMBER:", ''),
            (r"Choose Instance Management Option:", ''),
            (r"No model content or proprietary data will be sent.\n1- Yes\n2- No\n"
             r"ENTER THE NUMBER OF THE DESIRED CHOICE:", '2'),
        ]
        no_qa = [r'Installing\.\.\..*\n.*------.*\n\n.*============.*\n.*$']

        run_shell_cmd(cmd, qa_patterns=qa, qa_wait_patterns=no_qa)

        # fix permissions on install dir
        perms = stat.S_IRWXU | stat.S_IXOTH | stat.S_IXGRP | stat.S_IROTH | stat.S_IRGRP
        adjust_permissions(self.installdir, perms, recursive=False, relative=False)

        # also install Python bindings if Python is included as a dependency
        if self.with_python:
            cwd = change_dir(os.path.join(self.installdir, 'python'))
            run_shell_cmd("python setup.py install --prefix=%s" % self.installdir)
            change_dir(cwd)

    def det_bindir(self):
        """Determine CPLEX bin subdirectory."""

        # avoid failing miserably under --module-only --force
        if os.path.exists(self.installdir) and os.listdir(self.installdir):
            bin_glob = 'cplex/bin/x86-64*'
            change_dir(self.installdir)
            bins = glob.glob(bin_glob)

            if len(bins) == 1:
                self.bindir = bins[0]
            elif len(bins) > 1:
                raise EasyBuildError("More than one possible path for bin found: %s", bins)
            else:
                raise EasyBuildError("No bins found using %s in %s", bin_glob, self.installdir)
        else:
            self.bindir = 'UNKNOWN'

    def make_module_extra(self):
        """Add bin dirs and lib dirs and set CPLEX_HOME and CPLEXDIR"""
        txt = super(EB_CPLEX, self).make_module_extra()

        # avoid failing miserably under --module-only --force
        if os.path.exists(self.installdir):
            cwd = change_dir(self.installdir)
            bins = glob.glob(os.path.join('*', 'bin', 'x86-64*'))
            libs = glob.glob(os.path.join('*', 'lib', 'x86-64*', '*pic'))
            change_dir(cwd)
        else:
            bins = []
            libs = []

        txt += self.module_generator.prepend_paths('PATH', [path for path in bins])
        txt += self.module_generator.prepend_paths('LD_LIBRARY_PATH', [path for path in bins + libs])

        txt += self.module_generator.set_environment('CPLEX_HOME', os.path.join(self.installdir, 'cplex'))
        txt += self.module_generator.set_environment('CPLEXDIR', os.path.join(self.installdir, 'cplex'))

        self.log.debug("make_module_extra added %s" % txt)
        return txt

    def sanity_check_step(self):
        """Custom sanity check for CPLEX"""

        if self.bindir is None:
            self.det_bindir()

        binaries = ['cplex', 'cplexamp']
        if LooseVersion(self.version) < LooseVersion('12.8'):
            binaries.append('convert')

        custom_paths = {
            'files': [os.path.join(self.bindir, x) for x in binaries],
            'dirs': [],
        }
        custom_commands = []

        if self.with_python:
            custom_commands.append("python -s -c 'import cplex'")
            custom_commands.append("python -s -c 'import docplex'")

        super(EB_CPLEX, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
