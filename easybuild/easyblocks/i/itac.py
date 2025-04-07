# #
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
# #
"""
EasyBuild support for installing the Intel Trace Analyzer and Collector (ITAC), implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.intelbase import IntelBase
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS
from easybuild.tools.run import run_shell_cmd


class EB_itac(IntelBase):
    """
    Class that can be used to install itac
    - minimum version suported: 2019.x
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'preferredmpi': ['impi3', "Preferred MPI type", CUSTOM],
        }
        return IntelBase.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Constructor, initialize class variables."""
        super().__init__(*args, **kwargs)

        if LooseVersion(self.version) < LooseVersion('2019'):
            raise EasyBuildError(
                f"Version {self.version} of {self.name} is unsupported. Mininum supported version is 2019.0."
            )

        # add cutom paths to the module load environment
        self.module_load_environment.PATH = ['bin', 'bin/intel64', 'bin64']
        self.module_load_environment.LD_LIBRARY_PATH = ['lib', 'lib/intel64', 'lib64', 'slib']
        # avoid software building against itac
        self.module_load_environment.remove('LIBRARY_PATH')
        for disallowed_var in self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS):
            self.module_load_environment.remove(disallowed_var)

    def prepare_step(self, *args, **kwargs):
        """
        Custom prepare step for itac: don't require runtime license for oneAPI versions (>= 2021)
        """
        if LooseVersion(self.version) >= LooseVersion('2021'):
            kwargs['requires_runtime_license'] = False

        super(EB_itac, self).prepare_step(*args, **kwargs)

    def install_step_classic(self):
        """
        Actual installation for versions prior to 2021.x

        - create silent cfg file
        - execute command
        """
        super(EB_itac, self).install_step_classic(silent_cfg_names_map=None)
        # since itac v9.0.1 installer create itac/<version> subdir, so stuff needs to be moved afterwards
        super(EB_itac, self).move_after_install()

    def install_step_oneapi(self, *args, **kwargs):
        """
        Actual installation for versions 2021.x onwards.
        """
        # require that EULA is accepted
        intel_eula_url = 'https://software.intel.com/content/www/us/en/develop/articles/end-user-license-agreement.html'
        self.check_accepted_eula(name='Intel-oneAPI', more_info=intel_eula_url)

        # exactly one "source" file is expected: the (offline) installation script
        if len(self.src) == 1:
            install_script = self.src[0]['name']
        else:
            src_fns = ', '.join([x['name'] for x in self.src])
            raise EasyBuildError("Expected to find exactly one 'source' file (installation script): %s", src_fns)

        cmd = ' '.join([
            "sh %s" % install_script,
            '-a',
            '-s',
            "--eula accept",
            "--install-dir=%s" % self.installdir,
        ])

        run_shell_cmd(cmd)

        # itac installer create itac/<version> subdir, so stuff needs to be moved afterwards
        super(EB_itac, self).move_after_install()

    def sanity_check_step(self):
        """Custom sanity check paths for ITAC."""

        custom_paths = {
            'files': ["include/%s" % x for x in ["i_malloc.h", "VT_dynamic.h", "VT.h", "VT.inc"]],
            'dirs': ["bin", "lib", "slib"],
        }

        super(EB_itac, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Overwritten from IntelBase to add extra txt"""
        txt = super(EB_itac, self).make_module_extra()
        txt += self.module_generator.set_environment('VT_ROOT', self.installdir)
        txt += self.module_generator.set_environment('VT_MPI', self.cfg['preferredmpi'])
        txt += self.module_generator.set_environment('VT_ADD_LIBS', "-ldwarf -lelf -lvtunwind -lnsl -lm -ldl -lpthread")
        txt += self.module_generator.set_environment('VT_LIB_DIR', self.installdir + "/lib")
        txt += self.module_generator.set_environment('VT_SLIB_DIR', self.installdir + "/slib")
        return txt
