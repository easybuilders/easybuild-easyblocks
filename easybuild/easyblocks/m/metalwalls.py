##
# Copyright 2009-2023 Ghent University
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
EasyBuild support for `metalwalls`, implemented as an easyblock

@author: Davide Grassano (CECAM, EPFL)
"""
import os

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd

from easybuild.easyblocks.generic.makecp import MakeCp


class EB_MetalWalls(MakeCp):
    """Support for building and installing `metalwalls`."""

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to `metalwalls`."""
        super(EB_MetalWalls, self).__init__(*args, **kwargs)

        self._build_python_interface = False


    def configure_step(self):
        """Custom configuration procedure for `metalwalls`."""
        comp_fam = self.toolchain.comp_family()

        f90flags = os.getenv('F90FLAGS', '').split(' ')
        fppflags = os.getenv('FPPFLAGS', '').split(' ')
        ldflags = os.getenv('LDFLAGS', '').split(' ')
        f90wrap = ''
        f2py = ''
        fcompiler = ''

        if comp_fam == toolchain.INTELCOMP:
            jflag = '-module'
            fppflags = ['-fpp']
        elif comp_fam == toolchain.GCC:
            jflag = '-J'
            fppflags = ['-cpp']
        else:
            raise EasyBuildError('Unsupported compiler family: %s' % comp_fam)

        # https://gitlab.com/ampere2/metalwalls/-/wikis/install#plumed
        plumed = get_software_root('PLUMED')
        f90wrap = get_software_root('f90wrap')

        tpl_rgx = 'alltests\.append(suite_%s)'
        if plumed:
            f90flags += ['-fallow-argument-mismatch'] # Code inside ifdef causes mismatch errors
            fppflags += ['-DMW_USE_PLUMED']
            cmd = ['plumed', 'patch', '--new', 'mw2']
            run_cmd(' '.join(cmd), log_all=False, log_ok=False, simple=False, regexp=False)
            cmd = ['plumed', 'patch', '--patch', '--shared', '--engine', 'mw2']
            run_cmd(' '.join(cmd), log_all=True, simple=False)
        else:
            self.log.info('PLUMED not found, excluding from test-suite')
            rgx = tpl_rgx % 'plumed'
            cmd = ['sed', '-i', "'s/^\( \+\)%s$/\\1pass # %s/'" % (rgx, rgx), 'tests/regression_tests.py']
            cmd = ['sed', '-i', "'s/%s/pass/'" % rgx, 'tests/regression_tests.py']
            run_cmd(' '.join(cmd), log_all=True, simple=False)

        if f90wrap:
            if not get_software_root('mpi4py'):
                raise EasyBuildError('Building the Python interface requires mpi4py')
            self._build_python_interface = True
            f90wrap = 'f90wrap'
            f2py = 'f2py'
            fcompiler = os.getenv('F90_SEQ')
            f90flags += ['-fPIC']
            self.cfg.update('build_cmd_targets', 'python')
        else:
            self.log.info('f90wrap not found, excluding python interface from test-suite')
            rgx = tpl_rgx % 'python_interface'
            cmd = ['sed', '-i', "'s/%s/pass/'" % rgx, 'tests/regression_tests.py']
            run_cmd(' '.join(cmd), log_all=True, simple=False)

        # Add libraries with LAPACK support
        lapack_shared_libs = os.getenv('LAPACK_SHARED_LIBS', None)
        if not lapack_shared_libs:
            raise EasyBuildError('Must use a toolchain with LAPACK support')
        extra_libs = lapack_shared_libs.replace('.so', '').split(',')
        extra_libs = [_[3:] for _ in extra_libs if _.startswith('lib')]
        ldflags += ['-l%s' % lib for lib in extra_libs]

        # Write the `config.mk` file
        configmk = os.path.join(self.cfg['start_dir'], 'config.mk')
        with open(configmk, 'w') as f:
            f.write('F90FLAGS := %s\n' % ' '.join(f90flags))
            f.write('FPPFLAGS := %s\n' % ' '.join(fppflags))
            f.write('LDFLAGS := %s\n' % ' '.join(ldflags))
            f.write('F90WRAP := %s\n' % f90wrap)
            f.write('F2PY := %s\n' % f2py)
            f.write('FCOMPILER := %s\n' % fcompiler)
            f.write('J := %s\n' % jflag)

        with open(configmk, 'r') as f:
            self.log.info('Contents of generated `config.mk`:\n%s' % f.read())

    def test_step(self):
        """
        Test the compilation using `metalwalls`'s test suite.
        """

        if self._build_python_interface:
            ppath = os.getenv('PYTHONPATH', '')
            ppath = os.path.join(self.cfg['start_dir'], 'build', 'python') + ':' + ppath
            self.log.info('Setting PYTHONPATH for testing to %s' % ppath)
            env.setvar('PYTHONPATH', ppath)

        super(EB_MetalWalls, self).test_step()

    def make_module_extra(self, extra=None):
        """Add custom entries to module."""

        txt = super(EB_MetalWalls, self).make_module_extra()

        if self._build_python_interface:
            txt += self.module_generator.prepend_paths('PYTHONPATH', 'python')

        return txt
