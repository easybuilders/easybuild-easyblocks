##
# Copyright 2020-2020 Ghent University
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
EasyBuild support for building and installing ADIOS, implemented as an easyblock

@author: Ake Sandgren (HPC2N, Umea University)
"""
import os

from easybuild.easyblocks.generic.cmakepythonpackage import CMakePythonPackage
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import change_dir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_ADIOS(CMakePythonPackage):
    """Support for building/installing ADIOS."""

    def install_step(self):
        """Custom install step for ADIOS."""

        super(EB_ADIOS, self).install_step()

        # Create numpy wrappers
        if get_software_root('SciPy-bundle'):
            newpath = os.pathsep.join([os.getenv('PATH', ''), os.path.join(self.installdir, 'bin')])
            setvar('PATH', newpath)
            change_dir(os.path.join(self.cfg['start_dir'], 'wrappers', 'numpy'))

            setup_list = ['']
            mpi = ''
            if self.toolchain.get_flag('usempi'):
                setup_list.append('_mpi')
                mpi = 'MPI=y'

            cmd = ' '.join([
                'make',
                'CYTHON=y',
                mpi,
                'python',
            ])
            run_cmd(cmd, log_all=True, simple=True)

            for setup_type in setup_list:
                cmd = ' '.join([
                    'python',
                    'setup%s.py' % setup_type,
                    'install',
                    '--prefix=%s' % self.installdir,
                ])
                run_cmd(cmd, log_all=True, simple=True)

    def sanity_check_step(self):
        """Custom sanity check for ADIOS."""

        file_list = [os.path.join('bin', x) for x in ['adios_list_methods', 'bpappend']]
        dir_list = [os.path.join('etc', 'skel', 'templates'), os.path.join('lib', 'python')]
        custom_paths = {
            'files': file_list,
            'dirs': dir_list,
        }
        return super(EB_ADIOS, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom environment variables for ADIOS."""

        txt = self.module_generator.prepend_paths('PYTHONPATH', [os.path.join('lib', 'python')])
        txt += super(EB_ADIOS, self).make_module_extra()

        return txt
