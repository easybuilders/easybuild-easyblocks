##
# Copyright 2018-2018 Ghent University
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
EasyBuild support for installing software using Spack, implemented as an easyblock.

@author: Kenneth Hoste (Ghent University)
"""
import os

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, mkdir, symlink, which, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd
from easybuild.tools.toolchain import DUMMY_TOOLCHAIN_NAME


class Spack(EasyBlock):
    """
    Support for installing software with Spack
    """

    def __init__(self, *args, **kwargs):
        """Constructor for Spack easyblock."""
        super(Spack, self).__init__(*args, **kwargs)

        self.spack_dir = None
        self.spack_spec = None

    def configure_step(self, cmd_prefix=''):
        """
        Configure step: prepare Spack for use and configure it
        """

        # copy Spack to build directory
        # this is required to configure it for the software installation(s) that will be performed
        spack_root = get_software_root('Spack')
        if spack_root is None:
            spack = which('spack')
            if spack:
                spack_root = os.path.dirname(os.path.dirname(spack))
            else:
                raise EasyBuildError("Failed to find Spack!")

        self.spack_dir = os.path.join(self.builddir, 'spack')
        copy_dir(spack_root, self.spack_dir)

        # make sure right 'spack' command is picked up
        env.setvar('PATH', '%s:%s' % (os.path.join(self.spack_dir, 'bin'), os.getenv('PATH')))

        # make Spack aware of available compilers (incl. toolchain compiler)
        run_cmd("spack compiler add --scope site")

        # instruct Spack where to install software
        spack_cfg_txt = '\n'.join([
            'config:',
            '  install_tree: %s' % os.path.join(self.installdir, 'spack'),
        ])
        write_file(os.path.join(self.spack_dir, 'etc', 'spack', 'config.yaml'), spack_cfg_txt)

        self.spack_spec = self.name.lower() + '@' + self.version

        # make Spack aware of available dependencies
        spack_pkgs_lines = ['packages:']

        # Python is a special case (OK to use system Python)
        python_root = os.path.dirname(os.path.dirname(which('python')))
        out, ec = run_cmd('python --version', simple=False)
        if ec:
            raise EasyBuildError("Failed to determine (system) Python version: %s" % out)
        else:
            python_ver = out.strip().split(' ')[-1]

        spack_pkgs_lines.extend([
            '  python:',
            '    paths:',
            '      python@%s: %s' % (python_ver, python_root),
        ])

        write_file(os.path.join(self.spack_dir, 'etc', 'spack', 'packages.yaml'), '\n'.join(spack_pkgs_lines))

    def build_step(self, verbose=False, path=None):
        """
        Build step: ...
        """
        pass

    def install_step(self):
        """
        Install step: ...
        """
        cmd = ["spack install %s " % self.spack_spec]

        # instruct Spack to use right compiler when a non-dummy toolchain is used
        if self.toolchain.name != DUMMY_TOOLCHAIN_NAME:
            comp_name = self.toolchain.COMPILER_MODULE_NAME[0]
            comp_version = get_software_version(comp_name)
            if comp_name == 'GCCcore':
                comp_name = 'gcc'
            else:
                comp_name = comp_name.lower()
            cmd += '%' + comp_name + '@' + comp_version

        run_cmd(cmd)

    def post_install_step(self):
        """
        Symlink installed software into top-level installation prefix
        """
        super(Spack, self).post_install_step()

        run_cmd("spack view symlink %s %s" % (self.installdir, self.spack_spec))
