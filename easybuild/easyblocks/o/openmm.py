##
# Copyright 2009-2015 Ghent University
# Copyright 2015-2016 Stanford University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
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
EasyBuild support for building and installing OpenMM, implemented as an easyblock

@author: Stephane Thiell (Stanford University)
"""
import os
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.build_log import EasyBuildError


class EB_OpenMM(CMakeMake):
    """Support for building/installing OpenMM."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for OpenMM."""
        super(EB_OpenMM, self).__init__(*args, **kwargs)

        self.example = None

    def configure_step(self):
        """Custom configuration procedure for OpenMM."""

        if LooseVersion(self.version) < LooseVersion('6.3'):
            self.log.warn("OpenMM easyblocks not tested for older version of OpenMM")

        # build a release build
        self.cfg.update('configopts', "-DCMAKE_BUILD_TYPE=Release")

        #self.cfg.update('configopts', "-DOPENMM_BUILD_SHARED_LIB=OFF")
        #self.cfg.update('configopts', "-DOPENMM_BUILD_STATIC_LIB=ON")

        # CUDA is required
        cuda = get_software_root('CUDA')
        if cuda:
            self.cfg.update('configopts', "-DCUDA_TOOLKIT_ROOT_DIR=%s" % cuda)
        else:
            raise EasyBuildError("CUDA not found")

        doxygen = get_software_root('Doxygen')
        if not doxygen:
            raise EasyBuildError("Doxygen not found")

        doxygen = get_software_root('SWIG')
        if not doxygen:
            raise EasyBuildError("SWIG not found")

        # complete configuration with configure_method of parent
        out = super(EB_OpenMM, self).configure_step()

    def test_step(self):
        """Custom built-in test procedure for OpenMM."""

        # this has to be defined to avoid a fallback to hardcoded path /usr/local/cuda/bin/nvcc
        env.setvar('OPENMM_CUDA_COMPILER', 'nvcc')

        cmd = "make test"
        (out, ec) = run_cmd(cmd, simple=False, log_all=False, log_ok=False)
        if ec:
            # just provide output in log file, but ignore things if it fails
            self.log.warning("OpenMM tests failed (exit code: %s): %s" % (ec, out))
        else:
            self.log.info("Successful OpenMM tests completed: %s" % out)

    def install_step(self):
        """Custom install procedure for OpenMM."""
        super(EB_OpenMM, self).install_step()

        env.setvar('OPENMM_INCLUDE_PATH', os.path.join(self.installdir, 'include'))
        env.setvar('OPENMM_LIB_PATH', os.path.join(self.installdir, 'lib'))

        pyinstalldir = os.path.join(self.installdir, 'python-wrappers')
        args = "install --prefix=%(path)s --install-lib=%(path)s/lib" % {'path': pyinstalldir}
        try:
            os.mkdir(pyinstalldir)
        except OSError, err:
            raise EasyBuildError("Failed to create python-wrappers dir %s: %s", pyinstalldir, err)

        cmd = "cd python; python setup.py build && python setup.py install %s" % args
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def sanity_check_step(self):
        """Custom sanity check for OpenMM."""

        custom_paths = {
                        'files': ['lib/libOpenMM.so', 'lib/plugins/libOpenMMCUDA.so'],
                        'dirs': ['lib', 'lib/plugins', 'include/openmm'],
                       }

        super(EB_OpenMM, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for OpenMM."""

        txt = super(EB_OpenMM, self).make_module_extra()

        txt += self.module_generator.set_environment("OPENMM_CUDA_COMPILER", "nvcc")
        txt += self.module_generator.load_module("CUDA/%s" % get_software_version("CUDA"))
        txt += self.module_generator.prepend_paths('PYTHONPATH', ["python-wrappers/lib"])

        return txt
