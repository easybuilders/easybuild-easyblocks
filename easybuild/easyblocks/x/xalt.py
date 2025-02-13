##
# Copyright 2020-2025 NVIDIA
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for XALT, implemented as an easyblock
@author: Scott McMillan (NVIDIA)
@author: Kenneth Hoste (HPC-UGent)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_XALT(ConfigureMake):
    """Support for building and installing XALT."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'config_py': [None, "XALT site filter file", MANDATORY],
            'executable_tracking': [True, "Enable executable tracking", CUSTOM],
            'gpu_tracking': [None, "Enable GPU tracking", CUSTOM],
            'logging_url': [None, "Logging URL for transmission", CUSTOM],
            'mysql': [False, "Build with MySQL support", CUSTOM],
            'scalar_sampling': [True, "Enable scalar sampling", CUSTOM],
            'static_cxx': [False, "Statically link libstdc++ and libgcc_s", CUSTOM],
            'syshost': [None, "System name", MANDATORY],
            'transmission': [None, "Data tranmission method", MANDATORY],
            'file_prefix': [None, "XALT record files prefix", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize class variables."""
        super().__init__(*args, **kwargs)

        self.module_load_environment.COMPILER_PATH = 'bin'
        self.module_load_environment.PATH = 'bin'

        mod_env_headers = self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS)
        mod_env_libs = ['LD_LIBRARY_PATH', 'LIBRARY_PATH']
        mod_env_cmake = ['CMAKE_LIBRARY_PATH', 'CMAKE_PREFIX_PATH']
        for disallowed_var in mod_env_headers + mod_env_libs + mod_env_cmake:
            self.module_load_environment.remove(disallowed_var)
            self.log.debug(f"Purposely not updating ${disallowed_var} in {self.name} module file")

    def configure_step(self):
        """Custom configuration step for XALT."""

        # By default, XALT automatically appends 'xalt/<version>' to the
        # prefix, i.e., --prefix=/opt will actually install in
        # /opt/xalt/<version>.  To precisely control the install prefix and
        # not append anything to the prefix, use the configure option
        # '--with-siteControlledPrefix=yes'.
        # See https://xalt.readthedocs.io/en/latest/050_install_and_test.html
        self.cfg.update('configopts', '--with-siteControlledPrefix=yes')

        # XALT site filter config file is mandatory
        config_py = self.cfg['config_py']
        if config_py:
            if os.path.exists(config_py):
                self.cfg.update('configopts', '--with-config=%s' % config_py)
            else:
                raise EasyBuildError("Specified XALT configuration file %s does not exist!", config_py)
        else:
            error_msg = "Location of XALT configuration file must be specified via 'config_py' easyconfig parameter. "
            error_msg += "You can edit the easyconfig file, or use 'eb --try-amend=config_py=<path>'. "
            error_msg += "See https://xalt.readthedocs.io/en/latest/030_site_filtering.html for more information."
            raise EasyBuildError(error_msg)

        # XALT system name is mandatory
        if self.cfg['syshost']:
            self.cfg.update('configopts', '--with-syshostConfig=%s' % self.cfg['syshost'])
        else:
            error_msg = "The name of the system must be specified via the 'syshost' easyconfig parameter. "
            error_msg += "You can edit the easyconfig file, or use 'eb --try-amend=syshost=<string>'. "
            error_msg += "See https://xalt.readthedocs.io/en/latest/020_site_configuration.html for more information."
            raise EasyBuildError(error_msg)

        # Transmission method is mandatory
        if self.cfg['transmission']:
            self.cfg.update('configopts', '--with-transmission=%s' % self.cfg['transmission'])
        else:
            error_msg = "The XALT transmission method must be specified via the 'transmission' easyconfig parameter. "
            error_msg = "You can edit the easyconfig file, or use 'eb --try-amend=transmission=<string>'. "
            error_msg += "See https://xalt.readthedocs.io/en/latest/020_site_configuration.html for more information."
            raise EasyBuildError(error_msg)

        # GPU tracking
        if self.cfg['gpu_tracking'] is True:
            # User enabled
            self.cfg.update('configopts', '--with-trackGPU=yes')
        elif self.cfg['gpu_tracking'] is None:
            # Default value, enable GPU tracking if nvml.h is present
            # and the CUDA module is loaded
            cuda_root = get_software_root('CUDA')
            if cuda_root:
                nvml_h = os.path.join(cuda_root, "include", "nvml.h")
                if os.path.isfile(nvml_h):
                    self.cfg.update('configopts', '--with-trackGPU=yes')
                    self.cfg['gpu_tracking'] = True
        else:
            # User disabled
            self.cfg.update('configopts', '--with-trackGPU=no')

        # MySQL
        if self.cfg['mysql'] is True:
            self.cfg.update('configopts', '--with-MySQL=yes')
        else:
            self.cfg.update('configopts', '--with-MySQL=no')

        # If XALT is built with a more recent compiler than the system
        # compiler, then XALT likely will depend on symbol versions not
        # available in the system libraries. Link statically as a workaround.
        if self.cfg['static_cxx'] is True:
            self.cfg.update('configopts', 'LDFLAGS="${LDFLAGS} -static-libstdc++ -static-libgcc"')

        # XALT file prefix (optional). The default is $HOME/.xalt.d/ which
        # entails that record files are stored separately for each user.
        # If this option is specified, XALT will write to the specified
        # location for every user. The file prefix can also be modified
        # after the install using the XALT_FILE_PREFIX environment variable.
        if self.cfg['file_prefix']:
            self.cfg.update('configopts', '--with-xaltFilePrefix=%s' % self.cfg['file_prefix'])

        # Configure
        super(EB_XALT, self).configure_step()

    def make_module_extra(self, *args, **kwargs):
        txt = super(EB_XALT, self).make_module_extra(*args, **kwargs)

        txt += self.module_generator.prepend_paths('LD_PRELOAD', 'lib64/libxalt_init.%s' % get_shared_lib_ext())
        txt += self.module_generator.set_environment('XALT_DIR', self.installdir)
        txt += self.module_generator.set_environment('XALT_ETC_DIR', '%s' % os.path.join(self.installdir, 'etc'))
        txt += self.module_generator.set_environment('XALT_EXECUTABLE_TRACKING',
                                                     ('no', 'yes')[bool(self.cfg['executable_tracking'])])
        txt += self.module_generator.set_environment('XALT_GPU_TRACKING',
                                                     ('no', 'yes')[bool(self.cfg['gpu_tracking'])])
        if self.cfg['transmission'].lower() == 'curl' and self.cfg['logging_url']:
            txt += self.module_generator.set_environment('XALT_LOGGING_URL', self.cfg['logging_url'])
        txt += self.module_generator.set_environment('XALT_SCALAR_SAMPLING',
                                                     ('no', 'yes')[bool(self.cfg['scalar_sampling'])])

        # In order to track containerized executables, bind mount the XALT
        # directory in the Singularity container and preload the XALT library
        # https://xalt.readthedocs.io/en/latest/050_install_and_test.html#xalt-modulefile
        txt += self.module_generator.prepend_paths('SINGULARITY_BINDPATH', '')
        txt += self.module_generator.prepend_paths('SINGULARITYENV_LD_PRELOAD',
                                                   'lib64/libxalt_init.%s' % get_shared_lib_ext())

        return txt

    def sanity_check_step(self):
        """Custom sanity check"""
        custom_paths = {
            'files': ['bin/ld', 'bin/ld.gold', 'bin/xalt_extract_record',
                      'lib64/libxalt_init.%s' % get_shared_lib_ext()],
            'dirs': ['bin', 'libexec', 'sbin'],
        }
        custom_commands = ['xalt_configuration_report']

        super(EB_XALT, self).sanity_check_step(custom_commands=custom_commands,
                                               custom_paths=custom_paths)
