##
# Copyright 2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for building and installing libgpuarray and pygpu,
implemented as an easyblock

@author: Ake Sandgren (Umea University()
"""

import os

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.tools.filetools import mkdir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext

class EB_libgpuarray(CMakeMake):
    """Support for building/installing libgpuarray and pygpu."""

    def __init__(self, *args, **kwargs):
        """Initialize libgpuarray-specific variables."""
        super(EB_libgpuarray, self).__init__(*args, **kwargs)
        self.pylibdir = None
        self.libext = get_shared_lib_ext()

    def install_step(self):
        """
        Custom install step for libgpuarray.
        After install of libgpuarray, build and install pygpu.
        """

        super(EB_libgpuarray, self).install_step()

        # python setup.py build_ext -L $MY_PREFIX/lib -I $MY_PREFIX/include
        if get_software_root('Python'):
            self.pylibdir = det_pylibdir()
            pythonpath = os.environ.get('PYTHONPATH', '')
            env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))
            cmd = 'python setup.py build_ext -L %s/lib -I %s/include' % (self.installdir, self.installdir)
            run_cmd(cmd, log_all=True, simple=True, log_output=True)
            # Create the pylibdir path before installing.
            mkdir(os.path.join(self.installdir, self.pylibdir), parents=True)
            cmd = 'python setup.py install --prefix=%s' % self.installdir
            run_cmd(cmd, log_all=True, simple=True, log_output=True)

    def make_module_extra(self):
        """Add module entries for libgpuarray."""
        txt = super(EB_libgpuarray, self).make_module_extra()

        if self.pylibdir:
            txt += self.module_generator.prepend_paths('PYTHONPATH', self.pylibdir)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for libgpuarray."""

        dirs = [os.path.join('include', 'gpuarray'), self.pylibdir]

        includes = [
            'abi_version.h', 'buffer_blas.h', 'collectives.h', 'error.h', 'kernel.h',
            'array.h', 'buffer_collectives.h', 'config.h', 'ext_cuda.h', 'types.h',
            'blas.h', 'buffer.h', 'elemwise.h', 'extension.h', 'util.h',
        ]

        pyfile = [os.path.join(self.pylibdir, 'site.py')]

        libs = ['libgpuarray.%s' % self.libext, 'libgpuarray-static.a']

        custom_paths = {
            'files': [os.path.join('lib', l) for l in libs] +
                [os.path.join('include', 'gpuarray', x) for x in includes] + pyfile,
            'dirs': dirs,
        }
        super(EB_libgpuarray, self).sanity_check_step(custom_paths=custom_paths)
